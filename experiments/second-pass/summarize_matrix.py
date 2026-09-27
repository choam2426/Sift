#!/usr/bin/env python3
"""Summarize complete or explicitly partial 4x5 scores without claiming findings."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from prepare_matrix import VIEWS, jsonl


def key(row):
    return row["state_sha256"], row["question_sha256"], row["trial"]


def summarize(args):
    manifest = json.loads((args.prepared / "manifest.json").read_text())
    requests = jsonl(args.prepared / "requests.jsonl")
    expected = {key(row): row for row in requests}
    if len(expected) != len(requests) or len(requests) != manifest["unique_request_count"]:
        raise ValueError("request inventory is incomplete or duplicated")
    responses = jsonl(args.prepared / "responses.jsonl")
    actual = {}
    for row in responses:
        request_key = key(row)
        if request_key not in expected:
            raise ValueError("foreign response")
        prior = actual.get(request_key)
        if prior and not (prior["status"] == "error" and prior.get("http_status") == 402):
            raise ValueError("duplicate response after a final result")
        request = expected[request_key]
        if row["question_id"] != request["question_id"] or row["memberships"] != request["memberships"]:
            raise ValueError("response differs from planned request")
        actual[request_key] = row
    if len(actual) != len(expected) and not args.allow_incomplete:
        raise ValueError(f"run incomplete: {len(actual)}/{len(expected)} responses")

    label = json.loads(args.label_audit.read_text()) if args.label_audit else None
    if label and label["prepared_manifest_sha256"] != hashlib.sha256(
            (args.prepared / "manifest.json").read_bytes()).hexdigest():
        raise ValueError("label audit belongs to another prepared run")
    all_context = ({view: set(label["views"][view]["all_context_candidate_ids"])
                   for view in VIEWS} if label else {})
    conditions = defaultdict(lambda: {"planned": 0, "scored": 0, "unscored": 0,
                                      "error": 0, "pending": 0, "input_tokens": 0,
                                      "output_tokens": 0, "ranked_candidates": []})
    for request in requests:
        response = actual.get(key(request))
        status = response["status"] if response else "pending"
        if status not in {"scored", "unscored", "error", "pending"}:
            raise ValueError(f"unknown response status: {status}")
        for member in request["memberships"]:
            condition = conditions[(member["view"], request["question_id"])]
            condition["planned"] += 1
            condition[status] += 1
            usage = (response.get("usage") or {}) if response else {}
            condition["input_tokens"] += usage.get("input_tokens", 0)
            condition["output_tokens"] += usage.get("output_tokens", 0)
            if status == "scored":
                condition["ranked_candidates"].append((response["score"], member["candidate_id"]))

    rows = []
    for view in VIEWS:
        for question_id in (f"p{i}" for i in range(1, 6)):
            condition = conditions[(view, question_id)]
            ranked = sorted(condition.pop("ranked_candidates"), key=lambda item: (-item[0], item[1]))
            if len({candidate_id for _, candidate_id in ranked}) != len(ranked):
                raise ValueError("candidate scored more than once within one condition")
            item = {"view": view, "question_id": question_id, **condition}
            if label:
                item["all_context_candidate_count"] = len(all_context[view])
                best = next(((index, score) for index, (score, candidate_id) in enumerate(ranked, 1)
                             if candidate_id in all_context[view]), None)
                item["best_all_context_rank_among_scored"] = best[0] if best else None
                item["best_all_context_score"] = best[1] if best else None
                item["all_context_status_counts"] = {status: 0 for status in
                                                     ("scored", "unscored", "error", "pending")}
                for request in requests:
                    if request["question_id"] != question_id:
                        continue
                    response = actual.get(key(request))
                    status = response["status"] if response else "pending"
                    item["all_context_status_counts"][status] += sum(
                        member["view"] == view and member["candidate_id"] in all_context[view]
                        for member in request["memberships"])
            rows.append(item)
    report = {"status": ("partial_score_run_not_vulnerability_validation"
                         if len(actual) != len(expected) else
                         "score_run_complete_not_vulnerability_validation"),
              "source_revision": manifest["source_revision"],
              "questions_sha256": manifest["questions_sha256"],
              "planned_requests": len(requests), "recorded_response_rows": len(responses),
              "final_responses": len(actual),
              "request_status_counts": {status: (len(expected) - len(actual) if status == "pending" else
                                         sum(row["status"] == status for row in actual.values()))
                                        for status in ("scored", "unscored", "error", "pending")},
              "conditions": rows,
              "interpretation": "Ranks are among scored candidates only; labeled-code coverage is not a confirmed finding or a final 4x5 comparison."}
    if label:
        report["label_case_id"] = label["case_id"]
        report["label_audit_sha256"] = hashlib.sha256(args.label_audit.read_bytes()).hexdigest()
    if args.output.exists():
        raise ValueError("summary output exists; choose a new path")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "requests": len(requests),
                      "scored": report["request_status_counts"]["scored"],
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--label-audit", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    summarize(parser.parse_args())

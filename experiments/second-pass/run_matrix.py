#!/usr/bin/env python3
"""Execute a frozen 4x5 request inventory when explicitly enabled.

The default invocation only verifies and reports pending requests. This file
is prepared for a later experiment; it is not called by the preflight tools.
"""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from pathlib import Path

from prepare_matrix import VIEWS, canonical, digest, jsonl
from score_codedb_pilot import MODEL, api_key, score


def load(args):
    manifest_path = args.prepared / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["status"] != "prepared_no_model_calls" or manifest["condition_count"] != 20:
        raise ValueError("not a prepared 4x5 inventory")
    if manifest["model"] != MODEL:
        raise ValueError("scorer model differs from prepared model")
    question_path = args.prepared / "questions.json"
    if digest(question_path.read_bytes()) != manifest["questions_sha256"]:
        raise ValueError("prepared questions changed")
    questions = json.loads(question_path.read_text())
    if args.execute and questions["status"] != "frozen_for_experiment":
        raise ValueError("questions are still a proposal; freeze them before model calls")
    states = {}
    membership = set()
    for view in VIEWS:
        directory = args.inputs / view
        info = manifest["views"][view]
        for filename, field in (("manifest.json", "manifest_sha256"),
                                ("states.jsonl", "states_sha256"),
                                ("origins.jsonl", "origins_sha256")):
            if digest((directory / filename).read_bytes()) != info[field]:
                raise ValueError(f"{view}: input changed: {filename}")
        for row in jsonl(directory / "states.jsonl"):
            state_hash = digest(canonical(row["state"]))
            if state_hash != row["state_sha256"]:
                raise ValueError(f"{view}: state hash changed")
            prior = states.setdefault(state_hash, row["state"])
            if prior != row["state"]:
                raise ValueError("same state hash with different data")
            membership.add((view, row["candidate_id"], state_hash))
    requests = jsonl(args.prepared / "requests.jsonl")
    if len(requests) != manifest["unique_request_count"]:
        raise ValueError("request inventory changed")
    seen = set()
    for request in requests:
        key = (request["state_sha256"], request["question_sha256"], request["trial"])
        if key in seen or request["state_sha256"] not in states:
            raise ValueError("duplicate or unknown request")
        seen.add(key)
        question_id = request["question_id"]
        question = {question_id: {"type": "noul", "instructions":
                    questions["common_instruction"] + " " + questions["questions"][question_id]}}
        if digest(canonical(question)) != request["question_sha256"]:
            raise ValueError("question hash mismatch")
        for member in request["memberships"]:
            if (member["view"], member["candidate_id"], request["state_sha256"]) not in membership:
                raise ValueError("unknown condition membership")
    return manifest, questions, states, requests


def run(args):
    if args.workers < 1:
        raise ValueError("workers must be positive")
    _, questions, states, requests = load(args)
    responses_path = args.prepared / "responses.jsonl"
    latest = {}
    known = {(r["state_sha256"], r["question_sha256"], r["trial"]) for r in requests}
    if responses_path.exists():
        for row in jsonl(responses_path):
            key = (row["state_sha256"], row["question_sha256"], row["trial"])
            if key not in known:
                raise ValueError("foreign saved response")
            if row["requested_model"] != MODEL:
                raise ValueError("saved response model mismatch")
            prior = latest.get(key)
            if prior and not (prior["status"] == "error" and prior.get("http_status") == 402):
                raise ValueError("duplicate saved response after a final result")
            latest[key] = row
    retryable_402 = {key for key, row in latest.items()
                     if row["status"] == "error" and row.get("http_status") == 402}
    done = set(latest) - (retryable_402 if args.retry_http_402 else set())
    pending = [request for request in requests if
               (request["state_sha256"], request["question_sha256"], request["trial"]) not in done]
    if not args.execute:
        print(json.dumps({"status": "verified_no_model_calls", "planned": len(requests),
                          "recorded": len(latest), "http_402": len(retryable_402),
                          "completed": len(done), "pending": len(pending)}, ensure_ascii=False))
        return
    secret = api_key()
    def evaluate(request):
        question_id = request["question_id"]
        question = {question_id: {"type": "noul", "instructions":
                    questions["common_instruction"] + " " + questions["questions"][question_id]}}
        result = score(secret, states[request["state_sha256"]], question, question_id)
        return {"state_sha256": request["state_sha256"],
                "question_sha256": request["question_sha256"],
                "question_id": question_id, "trial": request["trial"],
                "requested_model": MODEL, "memberships": request["memberships"], **result}

    with responses_path.open("a") as output:
        def save(index, record):
            output.write(canonical(record).decode() + "\n")
            output.flush()
            print(f"{index}/{len(pending)} {record['question_id']} {record['status']}", flush=True)
            return record["status"] == "error" and record.get("http_status") == 402

        if args.workers == 1:
            for index, request in enumerate(pending, 1):
                if save(index, evaluate(request)):
                    raise RuntimeError("Jev returned HTTP 402; stopping requests")
        else:
            remaining = iter(pending)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                active = {}
                for _ in range(min(args.workers * 4, len(pending))):
                    request = next(remaining)
                    active[pool.submit(evaluate, request)] = request
                completed = 0
                halt = False
                while active:
                    finished, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in finished:
                        del active[future]
                        completed += 1
                        halt = save(completed, future.result()) or halt
                        if not halt:
                            request = next(remaining, None)
                            if request is not None:
                                active[pool.submit(evaluate, request)] = request
                if halt:
                    raise RuntimeError("Jev returned HTTP 402; stopping requests")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="make Jev API calls")
    parser.add_argument("--workers", type=int, default=1,
                        help="independent concurrent Jev requests (default: 1)")
    parser.add_argument("--retry-http-402", action="store_true",
                        help="retry previously recorded HTTP 402 requests")
    run(parser.parse_args())

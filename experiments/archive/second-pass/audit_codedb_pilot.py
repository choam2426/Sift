#!/usr/bin/env python3
"""Audit held-out code-location coverage only after pilot Jev responses exist."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-25-v4"
LABEL = ROOT / "experiments/second-pass/labels/cve-2026-14266.json"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main():
    states = read_jsonl(RUN / "states.jsonl")
    responses = read_jsonl(RUN / "responses.jsonl")
    if len(states) != len(responses) or any(row["status"] != "scored" for row in responses):
        raise ValueError("score the frozen pilot inputs before reading labels")
    by_response = {row["candidate_id"]: row for row in responses}
    if len(by_response) != len(responses):
        raise ValueError("duplicate response")
    label = json.loads(LABEL.read_text())
    essential = []
    for item in label["essential_context"]:
        relative, span = item["loc"].rsplit(":", 1)
        parts = span.split("-")
        essential.append((item["loc"], relative, int(parts[0]), int(parts[-1])))
    rows = []
    for candidate in states:
        state = candidate["state"]
        spans = {}
        for function in state["functions"]:
            spans.setdefault(function["file"], []).append(
                (function["start_line"], function["end_line"]))
        covered = [loc for loc, file, start, end in essential
                   if any(a <= start and end <= b for a, b in spans.get(file, []))]
        response = by_response[candidate["candidate_id"]]
        rows.append({"candidate_id": candidate["candidate_id"],
                     "state_expression": state["operation"]["state_expression"],
                     "score": response["score"], "essential_covered": covered,
                     "essential_count": len(covered),
                     "bug_site_function_included": any(
                         function["file"] == "C/XzDec.c" and
                         function["start_line"] == 580 and
                         function["symbol"] == "MixCoder_Code"
                         for function in state["functions"]),
                     "unresolved_call_count": len(state["unresolved_calls"])})
    rows.sort(key=lambda row: (-row["score"], row["candidate_id"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    audit = {"case_id": label["case_id"], "scope": "five_candidates_from_one_entry_only",
             "score_trials": 1, "essential_location_count": len(essential),
             "rows": rows}
    (RUN / "label-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

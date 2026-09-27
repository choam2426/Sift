#!/usr/bin/env python3
"""Audit frozen candidate code against a held-out mechanism label.

The label is read only after candidate inputs are generated. Results remain in
ignored run data and are never included in Jev state or the request inventory.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from matrix_facts import canonical, jsonl, sha
from prepare_matrix import VIEWS


def location(item):
    file, span = item["loc"].rsplit(":", 1)
    parts = span.split("-")
    return file, int(parts[0]), int(parts[-1])


def audit(args):
    prepared = json.loads((args.prepared / "manifest.json").read_text())
    if prepared["status"] != "prepared_no_model_calls":
        raise ValueError("candidate inputs are not frozen")
    label = json.loads(args.label.read_text())
    required = [(item["loc"], *location(item)) for item in label["essential_context"]]
    result = {"status": "held_out_code_coverage_only", "case_id": label["case_id"],
              "prepared_manifest_sha256": sha((args.prepared / "manifest.json").read_bytes()),
              "label_sha256": sha(args.label.read_bytes()), "views": {}}
    for view in VIEWS:
        path = args.inputs / view / "states.jsonl"
        if sha(path.read_bytes()) != prepared["views"][view]["states_sha256"]:
            raise ValueError(f"{view}: candidate states changed")
        rows = jsonl(path)
        any_count = all_count = bug_site_count = 0
        all_candidates = []
        for row in rows:
            state = row["state"]
            if sha(canonical(state)) != row["state_sha256"]:
                raise ValueError(f"{view}: candidate hash mismatch")
            spans = defaultdict(set)
            symbols = set()
            for function in state["functions"]:
                spans[function["file"]].update(range(function["start_line"],
                                                      function["end_line"] + 1))
                symbols.add((function["file"], function["start_line"], function["symbol"]))
            included = [name for name, file, start, end in required
                        if all(line in spans[file] for line in range(start, end + 1))]
            any_count += bool(included)
            all_count += len(included) == len(required)
            bug_site = label["target_function"].split(":", 1)[1]
            bug_file, bug_line, bug_name = bug_site.rsplit(":", 2)
            bug_site_count += (bug_file, int(bug_line), bug_name) in symbols
            if len(included) == len(required):
                all_candidates.append(row["candidate_id"])
        result["views"][view] = {"candidate_count": len(rows),
                                  "with_any_essential_context": any_count,
                                  "with_all_essential_context": all_count,
                                  "with_bug_site_function": bug_site_count,
                                  "all_context_candidate_ids": all_candidates}
    if args.output.exists():
        raise ValueError("audit output exists")
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({view: {key: value for key, value in data.items()
                             if key != "all_context_candidate_ids"}
                      for view, data in result["views"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--label", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args())

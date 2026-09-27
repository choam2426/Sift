#!/usr/bin/env python3
"""Audit CodeQL fact coverage against first-pass function inventory.

CodeQL may point to the first token of a function body while the first-pass
extractor starts at its declaration. Match by file, name, and contained source
line, and report compile-configuration alternatives separately.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path


FACT_FILES = ("functions", "calls", "call_arguments", "parameters", "parameter_accesses", "field_accesses",
              "conditions", "unresolved_calls", "local_value_steps",
              "guarded_effects", "observable_effects")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def audit(args):
    manifest = json.loads((args.facts / "manifest.json").read_text())
    if manifest["status"] != "neutral_facts_no_model_calls":
        raise ValueError("fact export is incomplete")
    for name, info in manifest["files"].items():
        if sha(args.facts / f"{name}.csv") != info["csv_sha256"]:
            raise ValueError(f"fact CSV changed: {name}")
    first = json.loads(args.first_manifest.read_text())
    if first["source_revision"] != manifest["source_revision"] or first["functions_sha256"] != sha(args.functions):
        raise ValueError("first-pass and CodeQL snapshot mismatch")
    units = read_jsonl(args.functions)
    by_file_name = defaultdict(list)
    for unit in units:
        by_file_name[(unit["file"], unit["name"])].append(unit)
    selected = read_jsonl(args.selected)
    selected_ids = {row["unit_id"] for row in selected}
    if not selected_ids <= {unit["id"] for unit in units}:
        raise ValueError("unknown selected unit")

    def match(row):
        file, line, name = row["col0"], int(row["col1"]), row["col2"]
        options = [unit for unit in by_file_name[(file, name)]
                   if unit["start_line"] <= line <= unit["end_line"]]
        if len(options) > 1:
            raise ValueError(f"ambiguous CodeQL location: {file}:{line}:{name}")
        return options[0] if options else None

    counts = {}
    matched_definitions = set()
    for name in FACT_FILES:
        with (args.facts / f"{name}.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        linked = [match(row) for row in rows]
        counts[name] = {"rows": len(rows), "linked_to_first_pass": sum(x is not None for x in linked),
                        "linked_to_selected": sum(x is not None and x["id"] in selected_ids for x in linked)}
        if name == "functions":
            matched_definitions = {x["id"] for x in linked if x is not None}
    missing_selected = [unit for unit in units if unit["id"] in selected_ids
                        and unit["id"] not in matched_definitions]
    report = {"status": "coverage_audit_no_model_calls", "source_revision": manifest["source_revision"],
              "fact_manifest_sha256": sha(args.facts / "manifest.json"),
              "first_pass_functions": len(units), "selected_origins": len(selected_ids),
              "matched_functions": len(matched_definitions),
              "matched_selected_origins": len(selected_ids & matched_definitions),
              "missing_selected_origins": [unit["id"] for unit in sorted(missing_selected, key=lambda u: u["id"])],
              "missing_selected_by_file": dict(sorted(Counter(unit["file"] for unit in missing_selected).items())),
              "fact_counts": counts}
    if args.output.exists():
        raise ValueError("output exists")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("selected_origins", "matched_selected_origins",
                                                     "missing_selected_origins")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--functions", type=Path, required=True)
    parser.add_argument("--first-manifest", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args())

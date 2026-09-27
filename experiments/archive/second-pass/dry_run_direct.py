#!/usr/bin/env python3
"""Build historical target-centered dry-run states from source-backed direct C calls.

These states are not the group-scoring input adopted in ADR 0007. This does not
call Jev. Labels are read only after every state has been written.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess


RULE_VERSION = "codeql-visible-direct-v1"
LIMIT_BYTES = 28_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def csv_rows(path, width):
    with path.open(newline="") as source:
        reader = csv.reader(source)
        header = next(reader)
        if header != [f"col{i}" for i in range(width)]:
            raise ValueError(f"unexpected CodeQL CSV columns: {path}")
        rows = list(reader)
    if any(len(row) != width for row in rows):
        raise ValueError(f"malformed CodeQL row: {path}")
    return rows


def source_lines(source_root, relative, cache):
    if relative not in cache:
        path = (source_root / relative).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError("source path is outside snapshot or absent: " + relative)
        cache[relative] = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    return cache[relative]


def excerpt(source_root, relative, start, end, cache):
    lines = source_lines(source_root, relative, cache)
    if not 1 <= start <= end <= len(lines):
        raise ValueError(f"invalid source span: {relative}:{start}-{end}")
    return "".join(lines[start - 1:end]).rstrip("\r\n")


def function_payload(row, key):
    return {
        "key": key,
        "file": row["file"],
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "symbol": row["name"],
        "code": row["code"],
    }


def relation_payload(from_key, to_key, evidence):
    return {
        "kind": "direct_call",
        "from": from_key,
        "to": to_key,
        "evidence": evidence,
    }


def state_bytes(state):
    return len(compact(state))


def percentiles(values):
    ordered = sorted(values)
    return {name: ordered[(len(ordered) - 1) * numerator // 100]
            for name, numerator in (("p50", 50), ("p90", 90), ("p95", 95), ("max", 100))}


def load_inputs(args):
    source_root = args.source_root.resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.run(["git", "-C", str(source_root), "diff", "--quiet", "HEAD", "--"],
                      check=False).returncode:
        raise ValueError("tracked source differs from pinned revision")

    units = jsonl(args.functions)
    by_id = {unit["id"]: unit for unit in units}
    if len(units) != 602 or len(by_id) != len(units):
        raise ValueError("expected 602 unique 7-Zip functions")
    lines_cache = {}
    for unit in units:
        actual = excerpt(source_root, unit["file"], unit["start_line"],
                         unit["end_line"], lines_cache)
        if actual != unit["code"]:
            raise ValueError("function body differs from source: " + unit["id"])

    first_manifest = json.loads(args.first_manifest.read_text())
    if (first_manifest["source_revision"] != revision
            or first_manifest["functions_sha256"] != digest(args.functions.read_bytes())
            or first_manifest["function_count"] != len(units)
            or first_manifest["input_profile"] != "code-only-v1"
            or first_manifest["requested_model"] != "jev-1.13.0"
            or first_manifest["threshold"] != 0.60):
        raise ValueError("first-pass manifest differs from pinned A input")

    selected = jsonl(args.selected)
    if len(selected) != 376 or len({row["unit_id"] for row in selected}) != len(selected):
        raise ValueError("expected 376 unique first-pass anchors")
    if selected != sorted(selected, key=lambda row: (-row["score"], row["unit_id"])):
        raise ValueError("first-pass anchors are not in pinned score order")
    for row in selected:
        if (row["unit_id"] not in by_id or row["score"] < 0.60
                or row["source_revision"] != revision
                or row["input_profile"] != first_manifest["input_profile"]
                or row["model"] != first_manifest["requested_model"]
                or row["question_sha256"] != first_manifest["question_sha256"]):
            raise ValueError("anchor differs from pinned first pass: " + row["unit_id"])
    return source_root, revision, units, by_id, selected, lines_cache


def graph(args, source_root, units, lines_cache):
    by_file_name = defaultdict(list)
    for unit in units:
        by_file_name[unit["file"], unit["name"]].append(unit)

    def resolve(relative, line, name):
        candidates = [unit for unit in by_file_name[relative, name]
                      if unit["start_line"] <= int(line) <= unit["end_line"]]
        if len(candidates) > 1:
            raise ValueError(f"ambiguous CodeQL definition: {relative}:{line}:{name}")
        return candidates[0] if candidates else None

    codeql_defs = csv_rows(args.definitions, 3)
    mapped_defs = {}
    for file, line, name in codeql_defs:
        unit = resolve(file, line, name)
        if unit:
            mapped_defs[file, line, name] = unit
    covered_ids = {unit["id"] for unit in mapped_defs.values()}

    rejected = Counter()
    edges = defaultdict(dict)
    for row in csv_rows(args.edges, 9):
        caller = mapped_defs.get(tuple(row[:3]))
        callee = mapped_defs.get(tuple(row[3:6]))
        if not caller:
            rejected["caller_not_in_inventory_or_variant"] += 1
            continue
        if not callee:
            rejected["callee_not_in_inventory_or_variant"] += 1
            continue
        relative, raw_start, raw_end = row[6:9]
        start, end = int(raw_start), int(raw_end)
        if relative != caller["file"] or not caller["start_line"] <= start <= end <= caller["end_line"]:
            rejected["callsite_outside_caller"] += 1
            continue
        code = excerpt(source_root, relative, start, end, lines_cache)
        if not re.search(r"\b" + re.escape(callee["name"]) + r"\b", code):
            rejected["target_name_not_visible_at_callsite"] += 1
            continue
        evidence = {"file": relative, "start_line": start,
                    "end_line": end, "code": code}
        key = (relative, start, end)
        edges[caller["id"], callee["id"]][key] = evidence

    resolved_edges = {
        pair: [points[key] for key in sorted(points)]
        for pair, points in edges.items()
    }
    unresolved = defaultdict(dict)
    for row in csv_rows(args.unresolved, 6):
        caller = mapped_defs.get(tuple(row[:3]))
        if not caller:
            continue
        relative, raw_start, raw_end = row[3:6]
        start, end = int(raw_start), int(raw_end)
        if relative != caller["file"] or not caller["start_line"] <= start <= end <= caller["end_line"]:
            continue
        code = excerpt(source_root, relative, start, end, lines_cache)
        key = (relative, start, end)
        unresolved[caller["id"]][key] = {
            "file": relative, "start_line": start, "end_line": end, "code": code,
        }
    unresolved = {unit_id: [points[key] for key in sorted(points)]
                  for unit_id, points in unresolved.items()}
    return covered_ids, resolved_edges, unresolved, rejected, len(codeql_defs)


def build_states(selected, by_id, covered_ids, edges, unresolved):
    neighbors = defaultdict(set)
    for caller, callee in edges:
        neighbors[caller].add(callee)
        neighbors[callee].add(caller)

    states = []
    records = []
    for anchor in selected:
        unit_id = anchor["unit_id"]
        unit = by_id[unit_id]
        state = {
            "target": function_payload(unit, "T"),
            "related_functions": [],
            "relations": [],
        }
        base_bytes = state_bytes(state)
        chosen = []
        excluded = []
        candidates = sorted(neighbors[unit_id],
                            key=lambda other: (0 if (unit_id, other) in edges else 1, other))
        if base_bytes > LIMIT_BYTES:
            excluded = [{"unit_id": other, "reason": "anchor_only_over_budget"}
                        for other in candidates]
        else:
            for other in candidates:
                key = f"R{len(chosen) + 1}"
                new_relations = []
                if (unit_id, other) in edges:
                    new_relations.append(relation_payload("T", key, edges[unit_id, other]))
                if (other, unit_id) in edges:
                    new_relations.append(relation_payload(key, "T", edges[other, unit_id]))
                trial = {
                    "target": state["target"],
                    "related_functions": state["related_functions"]
                        + [function_payload(by_id[other], key)],
                    "relations": state["relations"] + new_relations,
                }
                trial["relations"].sort(key=lambda relation: (
                    relation["kind"], relation["evidence"][0]["file"],
                    relation["evidence"][0]["start_line"], relation["to"]))
                if state_bytes(trial) <= LIMIT_BYTES:
                    state = trial
                    chosen.append(other)
                else:
                    excluded.append({"unit_id": other, "reason": "context_budget"})
        encoded = compact(state)
        if (len(encoded) > LIMIT_BYTES) != (base_bytes > LIMIT_BYTES):
            raise AssertionError("budget rule violated")
        states.append({"unit_id": unit_id, "state_sha256": digest(encoded), "state": state})
        records.append({
            "unit_id": unit_id,
            "first_pass_score": anchor["score"],
            "state_sha256": digest(encoded),
            "state_bytes": len(encoded),
            "anchor_only_over_budget": base_bytes > LIMIT_BYTES,
            "codeql_definition_matched": unit_id in covered_ids,
            "candidate_count": len(candidates),
            "selected_related_ids": chosen,
            "excluded_candidates": excluded,
            "relation_count": len(state["relations"]),
            "unresolved_outgoing_count": len(unresolved.get(unit_id, [])),
        })
    return states, records


def audit_label(label, states, records):
    by_record = {record["unit_id"]: record for record in records}
    parsed = []
    for item in label["essential_context"]:
        relative, span = item["loc"].rsplit(":", 1)
        parts = span.split("-")
        start, end = int(parts[0]), int(parts[-1])
        parsed.append((item["loc"], relative, start, end))

    results = []
    for record in states:
        full_spans = defaultdict(set)
        for function in [record["state"]["target"], *record["state"]["related_functions"]]:
            full_spans[function["file"]].update(range(function["start_line"], function["end_line"] + 1))
        all_spans = {relative: set(lines) for relative, lines in full_spans.items()}
        for relation in record["state"]["relations"]:
            for evidence in relation["evidence"]:
                all_spans.setdefault(evidence["file"], set()).update(
                    range(evidence["start_line"], evidence["end_line"] + 1))
        full = [loc for loc, relative, start, end in parsed
                if set(range(start, end + 1)) <= full_spans.get(relative, set())]
        any_code = [loc for loc, relative, start, end in parsed
                    if set(range(start, end + 1)) <= all_spans.get(relative, set())]
        if full or any_code:
            included_ids = [record["unit_id"], *by_record[record["unit_id"]]["selected_related_ids"]]
            results.append({"anchor_id": record["unit_id"],
                            "included_function_ids": included_ids,
                            "full_code_context": full,
                            "all_code_context": any_code})

    all_locations = {item[0] for item in parsed}
    complete = [item for item in results if set(item["full_code_context"]) == all_locations]
    return {
        "case_id": label["case_id"],
        "essential_locations": [item[0] for item in parsed],
        "anchors_with_all_essential_full_code": [item["anchor_id"] for item in complete],
        "anchors_with_bug_site_function": [item["anchor_id"] for item in results
            if label["target_function"] in item["included_function_ids"]],
        "bug_site_as_anchor": next((item for item in results
            if item["anchor_id"] == label["target_function"]), None),
        "anchors_with_any_essential_context": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--functions", type=Path, required=True)
    parser.add_argument("--first-manifest", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--definitions", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--unresolved", type=Path, required=True)
    parser.add_argument("--label", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory already exists; use a new run ID")

    source_root, revision, units, by_id, selected, lines_cache = load_inputs(args)
    covered_ids, edges, unresolved, rejected, codeql_def_count = graph(
        args, source_root, units, lines_cache)
    states, records = build_states(selected, by_id, covered_ids, edges, unresolved)

    args.output_dir.mkdir(parents=True)
    def write_json(name, value):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    def write_jsonl(name, values):
        (args.output_dir / name).write_text("".join(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
            for value in values))

    write_jsonl("states.jsonl", states)
    write_jsonl("records.jsonl", records)
    write_jsonl("unresolved_calls.jsonl", [
        {"unit_id": unit_id, "calls": calls} for unit_id, calls in sorted(unresolved.items())
    ])
    manifest = {
        "rule_version": RULE_VERSION,
        "status": "dry_run_no_model_calls",
        "source_revision": revision,
        "codeql_cli": "2.27.1",
        "state_byte_goal": LIMIT_BYTES,
        "relation_kind": "direct_call",
        "candidate_order": "direct_callee_then_direct_caller_then_unit_id",
        "relation_admission": "both definitions in first-pass inventory, callsite inside caller, target name visible in source excerpt",
        "source_files": 55,
        "source_functions": len(units),
        "anchors": len(selected),
        "inputs_sha256": {name: digest(path.read_bytes()) for name, path in (
            ("functions", args.functions), ("first_manifest", args.first_manifest),
            ("selected", args.selected), ("codeql_definitions", args.definitions),
            ("codeql_edges", args.edges), ("codeql_unresolved", args.unresolved))},
    }
    write_json("manifest.json", manifest)
    summary = {
        "anchors": len(records),
        "codeql_definitions": codeql_def_count,
        "inventory_functions_matched": len(covered_ids),
        "selected_anchor_definitions_matched": sum(record["codeql_definition_matched"] for record in records),
        "accepted_unique_function_pairs": len(edges),
        "accepted_callsite_evidence": sum(map(len, edges.values())),
        "rejected_edge_rows": dict(rejected),
        "unresolved_calls_in_inventory_functions": sum(map(len, unresolved.values())),
        "anchors_with_any_related_function": sum(bool(record["selected_related_ids"]) for record in records),
        "anchors_with_any_candidate": sum(record["candidate_count"] > 0 for record in records),
        "anchors_with_context_budget_exclusion": sum(any(item["reason"] == "context_budget"
            for item in record["excluded_candidates"]) for record in records),
        "anchors_only_over_budget": sum(record["anchor_only_over_budget"] for record in records),
        "anchors_with_unresolved_outgoing_call": sum(record["unresolved_outgoing_count"] > 0 for record in records),
        "state_bytes": percentiles([record["state_bytes"] for record in records]),
        "related_function_count": percentiles([len(record["selected_related_ids"]) for record in records]),
    }
    write_json("summary.json", summary)

    # Read the held-out label after all graph and state outputs have been written.
    label = json.loads(args.label.read_text())
    write_json("label_audit.json", audit_label(label, states, records))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

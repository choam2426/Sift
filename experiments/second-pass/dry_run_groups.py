#!/usr/bin/env python3
"""Build deduplicated group-scoring states from verified direct C calls.

This is a dry run of the proposed input format. It never calls Jev, and it
reads the held-out label only after the candidate states have been written.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path

from dry_run_direct import compact, digest, graph, load_inputs, percentiles


RULE_VERSION = "codeql-direct-groups-unbounded-v2"


def build_state(member_ids, by_id, edges):
    ordered = sorted(member_ids)
    keys = {unit_id: f"F{index}" for index, unit_id in enumerate(ordered, 1)}
    functions = [
        {
            "key": keys[unit_id],
            "file": by_id[unit_id]["file"],
            "start_line": by_id[unit_id]["start_line"],
            "end_line": by_id[unit_id]["end_line"],
            "symbol": by_id[unit_id]["name"],
            "code": by_id[unit_id]["code"],
        }
        for unit_id in ordered
    ]
    relations = [
        {
            "kind": "direct_call",
            "from": keys[caller],
            "to": keys[callee],
            "evidence": evidence,
        }
        for (caller, callee), evidence in edges.items()
        if caller in keys and callee in keys
    ]
    relations.sort(key=lambda relation: (
        relation["kind"], relation["from"], relation["to"],
        relation["evidence"][0]["file"],
        relation["evidence"][0]["start_line"],
    ))
    return {"functions": functions, "relations": relations}


def build_groups(selected, by_id, covered_ids, edges, unresolved, revision):
    neighbors = defaultdict(set)
    for caller, callee in edges:
        if caller != callee:
            neighbors[caller].add(callee)
            neighbors[callee].add(caller)

    groups_by_bytes = {}
    origins = []
    for selected_row in selected:
        origin_id = selected_row["unit_id"]
        members = {origin_id, *neighbors[origin_id]}
        state = build_state(members, by_id, edges)
        encoded = compact(state)
        if encoded not in groups_by_bytes:
            group_id = digest(revision.encode() + b"\0" + encoded)
            groups_by_bytes[encoded] = {
                "group_id": group_id,
                "state_sha256": digest(encoded),
                "state_bytes": len(encoded),
                "function_ids": sorted(members),
                "origin_ids": [],
                "state": state,
            }
        group = groups_by_bytes[encoded]
        group["origin_ids"].append(origin_id)
        origins.append({
            "origin_id": origin_id,
            "first_pass_score": selected_row["score"],
            "group_id": group["group_id"],
            "codeql_definition_matched": origin_id in covered_ids,
            "candidate_count": len(neighbors[origin_id]),
            "selected_related_ids": sorted(members - {origin_id}),
            "unresolved_outgoing_count": len(unresolved.get(origin_id, [])),
        })

    groups = sorted(groups_by_bytes.values(), key=lambda item: item["group_id"])
    if len({group["group_id"] for group in groups}) != len(groups):
        raise AssertionError("group ID collision")
    return groups, origins


def audit_label(label, groups):
    essential = []
    for item in label["essential_context"]:
        relative, span = item["loc"].rsplit(":", 1)
        parts = span.split("-")
        essential.append((item["loc"], relative, int(parts[0]), int(parts[-1])))

    with_any = []
    with_all = []
    with_bug_site = []
    for group in groups:
        if label["target_function"] in group["function_ids"]:
            with_bug_site.append(group["group_id"])
        spans = defaultdict(set)
        for function in group["state"]["functions"]:
            spans[function["file"]].update(range(
                function["start_line"], function["end_line"] + 1))
        included = [loc for loc, relative, start, end in essential
                    if set(range(start, end + 1)) <= spans.get(relative, set())]
        if included:
            with_any.append({"group_id": group["group_id"],
                             "origin_ids": group["origin_ids"],
                             "essential_locations": included})
        if len(included) == len(essential):
            with_all.append(group["group_id"])
    return {
        "case_id": label["case_id"],
        "essential_locations": [item[0] for item in essential],
        "groups_with_any_essential_full_code": with_any,
        "groups_with_all_essential_full_code": with_all,
        "groups_with_bug_site_function": with_bug_site,
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
    groups, origins = build_groups(
        selected, by_id, covered_ids, edges, unresolved, revision)

    args.output_dir.mkdir(parents=True)

    def write_json(name, value):
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def write_jsonl(name, values):
        (args.output_dir / name).write_text("".join(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
            for value in values))

    write_jsonl("states.jsonl", [
        {"group_id": group["group_id"],
         "state_sha256": group["state_sha256"],
         "state": group["state"]}
        for group in groups
    ])
    write_jsonl("groups.jsonl", [
        {key: value for key, value in group.items() if key != "state"}
        for group in groups
    ])
    write_jsonl("origins.jsonl", origins)
    write_jsonl("unresolved_calls.jsonl", [
        {"unit_id": unit_id, "calls": calls}
        for unit_id, calls in sorted(unresolved.items())
    ])
    manifest = {
        "rule_version": RULE_VERSION,
        "status": "dry_run_no_model_calls",
        "source_revision": revision,
        "codeql_cli": "2.27.1",
        "size_policy": "record_only_never_exclude_functions",
        "relation_kind": "direct_call",
        "group_boundary": "origin_and_all_one_step_verified_direct_calls",
        "group_identity": "source_revision_and_canonical_state_bytes",
        "relation_admission": "both definitions in first-pass inventory, callsite inside caller, target name visible in source excerpt",
        "source_functions": len(units),
        "origins": len(selected),
        "inputs_sha256": {name: digest(path.read_bytes()) for name, path in (
            ("functions", args.functions), ("first_manifest", args.first_manifest),
            ("selected", args.selected), ("codeql_definitions", args.definitions),
            ("codeql_edges", args.edges), ("codeql_unresolved", args.unresolved))},
    }
    write_json("manifest.json", manifest)
    summary = {
        "origins": len(origins),
        "unique_groups": len(groups),
        "duplicate_origin_inputs_removed": len(origins) - len(groups),
        "groups_with_multiple_origins": sum(len(group["origin_ids"]) > 1
                                            for group in groups),
        "groups_with_related_function": sum(len(group["function_ids"]) > 1
                                            for group in groups),
        "singleton_groups": sum(len(group["function_ids"]) == 1
                                for group in groups),
        "origins_with_unresolved_outgoing_call": sum(
            origin["unresolved_outgoing_count"] > 0 for origin in origins),
        "codeql_definitions": codeql_def_count,
        "inventory_functions_matched": len(covered_ids),
        "accepted_unique_function_pairs": len(edges),
        "accepted_callsite_evidence": sum(map(len, edges.values())),
        "rejected_edge_rows": dict(rejected),
        "unresolved_calls_in_inventory_functions": sum(map(len, unresolved.values())),
        "state_bytes": percentiles([group["state_bytes"] for group in groups]),
        "functions_per_group": percentiles([len(group["function_ids"])
                                            for group in groups]),
    }
    write_json("summary.json", summary)

    # Read held-out labels only after every state and provenance output is written.
    label = json.loads(args.label.read_text())
    write_json("label_audit.json", audit_label(label, groups))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

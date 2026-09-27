#!/usr/bin/env python3
"""Freeze a semantic-enriched copy of the five already-scored pilot inputs.

CodeQL contributes neutral local flow, branch, and pointer-write evidence.
The original function bodies and Jev question stay unchanged. This is a
controlled local comparison, not a general second-pass candidate builder.
"""

from collections import defaultdict, deque
import csv
import json
from pathlib import Path
import re
import subprocess

from pilot_codedb_state import ROOT, SOURCE_ROOT, Sources, compact, read_jsonl, sha


STAMP = "2026-09-26"
BASE = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-25-v4"
OUTPUT = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-26-v7"
FACTS = {
    name: Path(f"/tmp/sift-pilot-{name}-{STAMP}.csv")
    for name in ("local-value-steps", "guarded-effects", "branch-effects",
                 "function-pointer-writes")
}


def rows(name):
    with FACTS[name].open(newline="") as source:
        return list(csv.DictReader(source))


def key(row):
    return row["col0"], int(row["col1"]), row["col2"]


def span(source, row, first):
    names = ["col" + str(i) for i in range(first, first + 4)]
    numbers = [int(row[name]) for name in names]
    return {"file": row["col0"], "start_line": numbers[0],
            "start_column": numbers[1], "end_line": numbers[2],
            "end_column": numbers[3],
            "code": source.expr(row["col0"], *numbers)}


def canon(items):
    unique = {compact(item): item for item in items}
    return [unique[encoded] for encoded in sorted(unique)]


def coordinates(item):
    return [item["start_line"], item["start_column"],
            item["end_line"], item["end_column"]]


def build():
    if OUTPUT.exists():
        raise ValueError("output already exists; frozen runs must not be overwritten")
    base_manifest = json.loads((BASE / "manifest.json").read_text())
    revision = subprocess.check_output(
        ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != base_manifest["source_revision"] or subprocess.run(
        ["git", "-C", str(SOURCE_ROOT), "diff", "--quiet", "HEAD", "--"],
        check=False,
    ).returncode:
        raise ValueError("source revision no longer matches baseline")

    sources = Sources()
    inventory = read_jsonl(ROOT / "data/7zip.c.functions.jsonl")
    by_location = {(item["file"], item["start_line"], item["name"]): item
                   for item in inventory}
    if len(by_location) != len(inventory):
        raise ValueError("ambiguous function inventory")
    parameters = defaultdict(list)
    with Path("/tmp/sift-db-parameters-55-2026-09-25.csv").open(newline="") as source:
        for item in csv.DictReader(source):
            parameters[key(item)].append((item["col4"], item["col5"]))
    old = read_jsonl(BASE / "states.jsonl")
    if len(old) != 5:
        raise ValueError("pilot inventory changed")
    for item in old:
        if item["state_sha256"] != sha(compact(item["state"])):
            raise ValueError("base input hash mismatch")

    flow = defaultdict(list)
    for row in rows("local-value-steps"):
        left, right = span(sources, row, 4), span(sources, row, 8)
        if (left["start_line"], left["start_column"], left["end_line"],
                left["end_column"]) == (right["start_line"], right["start_column"],
                                         right["end_line"], right["end_column"]):
            continue  # identical source span supplies no visible relation
        flow[key(row)].append({"kind": row["kind"], "from": left, "to": right,
                               "scope": "intra_function"})

    controls = defaultdict(list)
    for name, kind, side_column in (
        ("guarded-effects", "guard_controls", "testIsTrue"),
        ("branch-effects", "branch_contains", "branchSide"),
    ):
        for row in rows(name):
            controls[key(row)].append({
                "kind": kind, "condition": span(sources, row, 3),
                "effect": span(sources, row, 7),
                "branch": row[side_column], "scope": "intra_function",
            })

    # Direct-call reachability is used only to find a write's provenance.
    # It is not converted into an indirect-call target edge.
    adjacency = defaultdict(list)
    with Path("/tmp/sift-db-call-arguments-55-2026-09-25.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            caller = key(row)
            callee = (row["col3"], int(row["col4"]), row["col5"])
            edge = (callee, row["col6"], int(row["col7"]))
            if edge not in adjacency[caller]:
                adjacency[caller].append(edge)

    writes = []
    for row in rows("function-pointer-writes"):
        assignment = span(sources, row, 3)
        value = span(sources, row, 7)
        match = re.fullmatch(r"&?([A-Za-z_][A-Za-z_0-9]*)", value["code"].strip())
        if not match:
            raise ValueError("function-pointer write target is not a function name")
        target_name = match.group(1)
        target = next((item for item in inventory if item["file"] == row["col0"]
                       and item["name"] == target_name), None)
        if target is None:
            raise ValueError("function-pointer target has no source body: " + target_name)
        writes.append({"setter": key(row), "assignment": assignment,
                       "value": value, "target": target})

    def shortest_path(starts, finish):
        queue = deque((start, []) for start in sorted(starts))
        seen = set(starts)
        while queue:
            current, path = queue.popleft()
            if current == finish:
                return path
            for callee, file, line in sorted(adjacency[current]):
                if callee not in seen:
                    seen.add(callee)
                    queue.append((callee, path + [{"caller": list(current),
                                                   "callee": list(callee),
                                                   "file": file, "line": line}]))
        return None

    enriched = []
    report = []
    for row in old:
        state = json.loads(json.dumps(row["state"]))
        members = {(func["file"], func["start_line"], func["symbol"]): func["key"]
                   for func in state["functions"]}
        member_by_key = {func["key"]: func for func in state["functions"]}
        effect_lines = defaultdict(set)
        for access in state["state_field_accesses"]:
            if access["syntactic_modification"]:
                effect_lines[access["function"]].add(access["line"])
        for call in state["unresolved_calls"]:
            effect_lines[call["function"]].add(call["start_line"])
        # Output writes are selected by parameter syntax, independent of
        # vulnerability labels and of the number of resulting relations.
        for location, fkey in members.items():
            output_parameters = [name for name, typ in parameters[location]
                                 if "*" in typ and not typ.lstrip().startswith("const ")]
            for control in controls[location]:
                effect = control["effect"]
                code = effect["code"].strip()
                if any(re.match(r"(?:\*\s*" + re.escape(name)
                                + r"\b|\(\s*\*\s*" + re.escape(name)
                                + r"\s*\))\s*(?:[+\-*/%&|^]?=|\+\+|--)", code)
                       for name in output_parameters):
                    effect_lines[fkey].add(effect["start_line"])
        selected_controls = [
            [fkey, edge["kind"], coordinates(edge["condition"]),
             coordinates(edge["effect"]), edge["branch"]]
            for location, fkey in members.items() for edge in controls[location]
            if edge["effect"]["start_line"] in effect_lines[fkey]
        ]
        condition_lines = defaultdict(set)
        for item in selected_controls:
            condition_lines[item[0]].add(item[2][0])
        selected_flow = [
            [fkey, edge["kind"], coordinates(edge["from"]), coordinates(edge["to"])]
            for location, fkey in members.items() for edge in flow[location]
            if (edge["from"]["start_line"] in effect_lines[fkey] | condition_lines[fkey]
                or edge["to"]["start_line"] in effect_lines[fkey] | condition_lines[fkey])
        ]
        state["relation_schema"] = {
            "coordinate_format": "[start_line,start_column,end_line,end_column], inclusive; source file comes from the function key",
            "projection": "Effects are writes to fields of this state, writes through nonconst pointer parameters, or unresolved calls. Keep controls of those effects and local steps touching those effects or their controlling conditions. No count or byte limit.",
            "local_value_steps": "[function_key, exact_value|taint_influence, from_coordinates, to_coordinates]; one intra-function CodeQL step, not a complete path",
            "controlled_effects": "[function_key, guard_controls|branch_contains, condition_coordinates, effect_coordinates, true|false|then|else]; guard is CFG control, branch is AST containment",
        }
        state["local_value_steps"] = canon(selected_flow)
        state["controlled_effects"] = canon(selected_controls)
        pointer_names = set()
        for call in state["unresolved_calls"]:
            pointer_names.update(re.findall(r"->([A-Za-z_][A-Za-z_0-9]*)\s*\(",
                                            call["code"]))
        bindings = []
        support = {}
        for write in writes:
            if "Code2" not in pointer_names:
                continue
            path = shortest_path(members, write["setter"])
            if path is None:
                continue
            setter = by_location.get(write["setter"])
            if setter is None:
                raise ValueError("setter body missing from inventory")
            for item in (setter, write["target"]):
                if (item["file"], item["start_line"], item["name"]) not in members:
                    support[item["id"]] = {"file": item["file"],
                                           "start_line": item["start_line"],
                                           "end_line": item["end_line"],
                                           "symbol": item["name"], "code": item["code"]}
            bindings.append({"field": "Code2", "status": "possible_write_not_call_target",
                             "setter": list(write["setter"]),
                             "direct_call_path_to_setter": path,
                             "assignment": write["assignment"],
                             "assigned_value": write["value"],
                             "possible_target": write["target"]["name"]})
        state["possible_indirect_bindings"] = canon(bindings)
        state["indirect_supporting_functions"] = [support[k] for k in sorted(support)]
        encoded = compact(state)
        candidate_id = sha(revision.encode() + b"\0" + encoded)
        enriched.append({"candidate_id": candidate_id, "state_sha256": sha(encoded),
                         "state_bytes": len(encoded), "state": state})
        report.append({"state_expression": state["operation"]["state_expression"],
                       "old_candidate_id": row["candidate_id"],
                       "new_candidate_id": candidate_id,
                       "old_state_bytes": row["state_bytes"],
                       "new_state_bytes": len(encoded),
                       "effect_line_count": sum(len(lines) for lines in effect_lines.values()),
                       "local_value_step_count": len(state["local_value_steps"]),
                       "controlled_effect_count": len(state["controlled_effects"]),
                       "possible_indirect_binding_count": len(bindings),
                       "indirect_supporting_function_count": len(support)})

    OUTPUT.mkdir(parents=True)
    (OUTPUT / "states.jsonl").write_text(
        "".join(compact(item).decode() + "\n" for item in enriched))
    (OUTPUT / "comparison-input.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    manifest = {"status": "enriched_pilot_input_no_jev_calls",
                "source_revision": revision,
                "base_states_sha256": sha((BASE / "states.jsonl").read_bytes()),
                "fact_csv_sha256": {name: sha(path.read_bytes())
                                    for name, path in FACTS.items()},
                "call_argument_csv_sha256": sha(Path(
                    "/tmp/sift-db-call-arguments-55-2026-09-25.csv").read_bytes()),
                "relation_policy": "all distinct source-spanned local value and control edges in member functions; possible pointer writes only when directly reachable from a member",
                "size_policy": "record_only_never_exclude_functions_or_relations"}
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()

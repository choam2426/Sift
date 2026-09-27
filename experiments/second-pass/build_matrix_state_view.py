#!/usr/bin/env python3
"""Build state-object candidates from exact source-level pointer forwarding.

An object root is a pointer parameter or an address-taken member of it.
The rule follows only direct calls that pass the same parameter expression;
other aliases and indirect calls remain unresolved. This is a proposal view.
"""

import argparse
from collections import defaultdict
from pathlib import Path
import re

from matrix_facts import FactSnapshot, canonical, sha, write_view


RULE = "matrix-state-exact-pointer-forwarding-v1-proposal"
ADDRESS_FIELD = re.compile(r"&\s*([A-Za-z_]\w*)\s*->\s*([A-Za-z_]\w*)")


def build(args):
    facts = FactSnapshot(args.facts, args.source_root, args.functions,
                         args.first_manifest, args.selected)
    params = defaultdict(dict)
    for row in facts.rows("parameters"):
        function = facts.unit(row["col0"], row["col1"], row["col2"])
        if function is not None:
            params[function["id"]][int(row["index"])] = {"name": row["col4"], "type": row["col5"]}
    calls = defaultdict(list)
    for row in facts.rows("call_arguments"):
        caller = facts.unit(row["col0"], row["col1"], row["col2"])
        callee = facts.unit(row["col3"], row["col4"], row["col5"])
        if caller is None or callee is None:
            continue
        index = int(row["index"])
        target_param = params[callee["id"]].get(index)
        if target_param is None or not target_param["name"]:
            continue
        expression = facts.expr(row["col12"], row["col13"], row["col14"],
                                row["col15"], row["col16"]).strip()
        call_site = {"file": row["col6"], "start_line": int(row["col7"]),
                     "start_column": int(row["col8"]), "end_line": int(row["col9"]),
                     "end_column": int(row["col10"])}
        if (call_site["file"] != caller["file"] or
                not caller["start_line"] <= call_site["start_line"] <= call_site["end_line"] <= caller["end_line"]):
            continue
        calls[caller["id"]].append({"callee": callee["id"], "argument_index": index,
                                     "argument": expression, "target_parameter": target_param["name"],
                                     "call_site": call_site})
    for items in calls.values():
        items.sort(key=lambda item: (item["call_site"]["file"],
                                     item["call_site"]["start_line"],
                                     item["call_site"]["start_column"], item["callee"],
                                     item["argument_index"]))

    fields = defaultdict(list)
    for row in facts.rows("field_accesses"):
        function = facts.unit(row["col0"], row["col1"], row["col2"])
        if function is None:
            continue
        fields[function["id"]].append({"name": row["col3"], "declaration": [row["col4"], int(row["col5"])],
                                        "qualifier": row["col11"], "file": row["col6"],
                                        "line": int(row["col7"]),
                                        "modified": row["col12"] == "modified"})
    candidates_by_id = {}
    origins = []
    unresolved = []
    for selected in facts.selected:
        origin = selected["unit_id"]
        root_params = [item for item in params[origin].values()
                       if item["name"] and ("*" in item["type"] or "&" in item["type"])
                       and not item["type"].lstrip().startswith("const ")]
        roots = set()
        for param in root_params:
            name = param["name"]
            if any(call["argument"] == name for call in calls[origin]):
                roots.add((name, None))
            for call in calls[origin]:
                match = ADDRESS_FIELD.fullmatch(call["argument"])
                if match and match.group(1) == name:
                    roots.add((name, match.group(2)))
        if not roots:
            unresolved.append({"origin_id": origin, "reason": "no_exact_pointer_forwarding_root"})
            continue
        for root_name, field_name in sorted(roots, key=lambda item: (item[0], item[1] or "")):
            expression = root_name if field_name is None else f"{root_name}->{field_name}"
            bindings = {(origin, root_name)} if field_name is None else set()
            transfers = []
            queue = [(origin, root_name, field_name is not None)]
            visited = set()
            while queue:
                function_id, parameter_name, need_address = queue.pop()
                if (function_id, parameter_name, need_address) in visited:
                    continue
                visited.add((function_id, parameter_name, need_address))
                for call in calls[function_id]:
                    expected = f"&{parameter_name}->{field_name}" if need_address else parameter_name
                    if re.sub(r"\s+", "", call["argument"]) != expected:
                        continue
                    target = (call["callee"], call["target_parameter"])
                    bindings.add(target)
                    transfers.append({"caller": function_id, "callee": call["callee"],
                                      "argument_index": call["argument_index"],
                                      "argument": call["argument"],
                                      "target_parameter": call["target_parameter"],
                                      "call_site": call["call_site"]})
                    queue.append((target[0], target[1], False))
            if not transfers:
                unresolved.append({"origin_id": origin, "object": expression,
                                   "reason": "no_verified_object_transfer"})
                continue
            members = {origin, *(function_id for function_id, _ in bindings)}
            keys, functions = facts.function_payload(members)
            relation_rows = []
            seen_transfers = set()
            for transfer in transfers:
                key = (transfer["caller"], transfer["callee"],
                       transfer["call_site"]["file"], transfer["call_site"]["start_line"],
                       transfer["call_site"]["start_column"], transfer["argument_index"])
                if key in seen_transfers:
                    continue
                seen_transfers.add(key)
                relation_rows.append({"kind": "pointer_argument_forwarding",
                                      "from": keys[transfer["caller"]],
                                      "to": keys[transfer["callee"]],
                                      "argument_index": transfer["argument_index"],
                                      "argument": transfer["argument"],
                                      "target_parameter": transfer["target_parameter"],
                                      "evidence": transfer["call_site"]})
            relation_rows.sort(key=lambda item: (item["evidence"]["file"],
                                                 item["evidence"]["start_line"],
                                                 item["evidence"]["start_column"],
                                                 item["from"], item["to"]))
            relevant_fields = {}
            for function_id, param_name in bindings:
                for item in fields[function_id]:
                    if item["qualifier"] != param_name:
                        continue
                    key = (item["name"], *item["declaration"])
                    relevant_fields[key] = {"name": item["name"],
                                            "declaration": {"file": item["declaration"][0],
                                                            "line": item["declaration"][1]}}
            declarations = facts.declarations(members)
            state = {"operation": {"entry": keys[origin], "object_expression": expression},
                     "functions": functions, "supporting_declarations": declarations,
                     "supporting_macros": facts.macros(declarations),
                     "state_fields": [relevant_fields[key] for key in sorted(relevant_fields)],
                     "relations": relation_rows,
                     "unresolved_dependencies": ["pointer aliases and reassignments are not resolved",
                                                 "indirect calls are not bound to targets"]}
            encoded = canonical(state)
            candidate_id = sha(facts.revision.encode() + b"\0" + encoded)
            if candidate_id not in candidates_by_id:
                candidates_by_id[candidate_id] = {
                    "candidate_id": candidate_id, "state_sha256": sha(encoded), "state": state}
            origins.append({"candidate_id": candidate_id, "origin_id": origin,
                            "member_ids": sorted(members), "first_pass_score": selected["score"],
                            "object_expression": expression})
    candidates = [candidates_by_id[key] for key in sorted(candidates_by_id)]
    write_view(args.output, "state", RULE, facts, candidates, origins, unresolved)
    print({"view": "state", "candidates": len(candidates),
           "origins_with_candidates": len({row["origin_id"] for row in origins}),
           "unresolved_records": len(unresolved)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--functions", type=Path, required=True)
    parser.add_argument("--first-manifest", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args())

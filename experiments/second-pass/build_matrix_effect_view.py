#!/usr/bin/env python3
"""Build one candidate per effect target in a selected function.

Return branches are one target; writes to a field or pointer expression are
grouped by destination. Reverse value and guard facts contribute context.
Possible influence is neither execution proof nor a vulnerability finding.
"""

import argparse
from collections import defaultdict
from pathlib import Path

from matrix_facts import FactSnapshot, canonical, sha, write_view
from matrix_value_graph import ValueGraph


RULE = "matrix-effect-target-contributors-v2-proposal"


def build(args):
    facts = FactSnapshot(args.facts, args.source_root, args.functions,
                         args.first_manifest, args.selected)
    graph = ValueGraph(facts)
    guards = defaultdict(list)
    for row in facts.rows("guarded_effects"):
        unit = facts.unit(row["col0"], row["col1"], row["col2"])
        if unit is None:
            continue
        effect_location = tuple(map(int, [row[f"col{i}"] for i in range(7, 11)]))
        guard_location = tuple(map(int, [row[f"col{i}"] for i in range(3, 7)]))
        guard = {"condition_location": list(guard_location),
                 "effect_location": list(effect_location),
                 "branch_value": row["testIsTrue"]}
        if guard not in guards[(unit["id"], effect_location)]:
            guards[(unit["id"], effect_location)].append(guard)

    candidates_by_id = {}
    origins = []
    unresolved = []
    for selected in facts.selected:
        origin = selected["unit_id"]
        effect_rows = graph.effects.get(origin, [])
        if not effect_rows:
            unresolved.append({"origin_id": origin, "reason": "no_observed_effect_fact"})
            continue
        groups = defaultdict(list)
        for effect in effect_rows:
            groups[(effect["kind"], effect["target"])].append(effect["node"])
        for (effect_kind, target), sinks in sorted(groups.items()):
            backwards = graph.reachable(sinks, reverse=True)
            members = {origin, *(node[0] for node in backwards)}
            keys, functions = facts.function_payload(members)
            relations = []
            seen_relations = set()
            for edge in graph.path_edges(backwards):
                if edge["source"][0] == edge["sink"][0]:
                    continue
                key = (edge["source"], edge["sink"], edge["kind"])
                if key in seen_relations:
                    continue
                seen_relations.add(key)
                relations.append({"kind": edge["kind"], "from": keys[edge["source"][0]],
                                  "to": keys[edge["sink"][0]],
                                  "evidence": edge["evidence"] or {}})
            relations.sort(key=lambda item: (item["kind"], item["from"], item["to"],
                                             canonical(item["evidence"])))
            selected_guards = []
            for sink in sorted(set(sinks)):
                selected_guards.extend(guards.get((origin, tuple(sink[1:])), []))
            selected_guards.sort(key=lambda item: (item["effect_location"],
                                                    item["condition_location"], item["branch_value"]))
            declarations = facts.declarations(members)
            state = {"operation": {"entry": keys[origin], "effect_kind": effect_kind,
                                   "effect_target": target,
                                   "effect_locations": [{"file": facts.by_id[origin]["file"],
                                                         "start_line": sink[1], "start_column": sink[2],
                                                         "end_line": sink[3], "end_column": sink[4]}
                                                        for sink in sorted(set(sinks))],
                                   "relation_status": "possible_contribution"},
                     "functions": functions, "supporting_declarations": declarations,
                     "supporting_macros": facts.macros(declarations),
                     "relations": relations, "conditions_controlling_effect": selected_guards,
                     "unresolved_dependencies": ["writes may be internal to the operation",
                                                 "indirect calls and pointer aliases may be missing"]}
            encoded = canonical(state)
            candidate_id = sha(facts.revision.encode() + b"\0" + encoded)
            if candidate_id not in candidates_by_id:
                candidates_by_id[candidate_id] = {
                    "candidate_id": candidate_id, "state_sha256": sha(encoded), "state": state}
            origins.append({"candidate_id": candidate_id, "origin_id": origin,
                            "member_ids": sorted(members), "first_pass_score": selected["score"],
                            "effect_kind": effect_kind, "effect_target": target})
    candidates = [candidates_by_id[key] for key in sorted(candidates_by_id)]
    write_view(args.output, "effect", RULE, facts, candidates, origins, unresolved)
    print({"view": "effect", "candidates": len(candidates),
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

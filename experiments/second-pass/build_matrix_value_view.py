#!/usr/bin/env python3
"""Build independently bounded candidates around one value origin each.

Each selected parameter or field read defines a value origin. The candidate
contains all supported paths from that origin to observed effects. The path
graph is possible influence; it does not claim a feasible execution.
"""

import argparse
from pathlib import Path

from matrix_facts import FactSnapshot, canonical, sha, write_view
from matrix_value_graph import ValueGraph


RULE = "matrix-value-origin-to-observed-effects-v1-proposal"


def build(args):
    facts = FactSnapshot(args.facts, args.source_root, args.functions,
                         args.first_manifest, args.selected)
    graph = ValueGraph(facts)
    effects = {item["node"]: item["kind"] for items in graph.effects.values() for item in items}
    candidates_by_id = {}
    origins = []
    unresolved = []
    for selected in facts.selected:
        origin = selected["unit_id"]
        sources = []
        for (function_id, index), items in graph.parameter_sources.items():
            if function_id == origin and items:
                sources.append(({"kind": "parameter", "index": index, "name": items[0]["name"]},
                                [item["node"] for item in items]))
        for (function_id, name, file, line), nodes in graph.field_sources.items():
            if function_id == origin and nodes:
                sources.append(({"kind": "field_read", "name": name,
                                 "field_declaration": {"file": file, "line": line}}, nodes))
        sources.sort(key=lambda item: canonical(item[0]))
        if not sources:
            unresolved.append({"origin_id": origin, "reason": "no_value_origin_fact"})
        for source, start_nodes in sources:
            reachable = graph.reachable(start_nodes)
            effect_nodes = sorted(node for node in reachable if node in effects)
            if not effect_nodes:
                unresolved.append({"origin_id": origin, "source": source,
                                   "reason": "no_supported_path_to_observed_effect"})
                continue
            path_nodes = graph.reachable(effect_nodes, reverse=True, allowed=reachable)
            path_edges = graph.path_edges(path_nodes)
            members = {node[0] for node in path_nodes}
            members.add(origin)
            keys, functions = facts.function_payload(members)
            transfer_rows = []
            seen = set()
            for edge in path_edges:
                if edge["source"][0] == edge["sink"][0]:
                    continue
                evidence = edge["evidence"] or {}
                key = (edge["source"], edge["sink"], edge["kind"])
                if key in seen:
                    continue
                seen.add(key)
                transfer_rows.append({"kind": edge["kind"],
                                      "from": keys[edge["source"][0]],
                                      "to": keys[edge["sink"][0]],
                                      "source_location": list(edge["source"][1:]),
                                      "sink_location": list(edge["sink"][1:]),
                                      "evidence": evidence})
            transfer_rows.sort(key=lambda item: (item["from"], item["to"],
                                                  item["source_location"], item["sink_location"]))
            effects_payload = [{"function": keys[node[0]], "kind": effects[node],
                                "location": list(node[1:])} for node in effect_nodes]
            declarations = facts.declarations(members)
            state = {"operation": {"value_origin": source, "entry": keys[origin],
                                   "relation_status": "possible_value_influence"},
                     "functions": functions, "supporting_declarations": declarations,
                     "supporting_macros": facts.macros(declarations),
                     "observed_effects": effects_payload, "relations": transfer_rows,
                     "unresolved_dependencies": ["local and interprocedural paths are not execution proofs",
                                                 "indirect calls and pointer aliases may be missing"]}
            encoded = canonical(state)
            candidate_id = sha(facts.revision.encode() + b"\0" + encoded)
            if candidate_id not in candidates_by_id:
                candidates_by_id[candidate_id] = {
                    "candidate_id": candidate_id, "state_sha256": sha(encoded), "state": state}
            origins.append({"candidate_id": candidate_id, "origin_id": origin,
                            "member_ids": sorted(members), "first_pass_score": selected["score"],
                            "source": source, "effect_count": len(effect_nodes)})
    candidates = [candidates_by_id[key] for key in sorted(candidates_by_id)]
    write_view(args.output, "value", RULE, facts, candidates, origins, unresolved)
    print({"view": "value", "candidates": len(candidates),
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

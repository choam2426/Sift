#!/usr/bin/env python3
"""Build the proposed call-flow view from pinned CodeQL direct calls.

One candidate starts at one source-backed call in a selected function and
contains that call's statically resolved downstream call closure. No hop or
size limit is used. Other view builders use the same fact snapshot separately.
"""

import argparse
from collections import defaultdict
from pathlib import Path

from matrix_facts import FactSnapshot, canonical, sha, write_view


RULE = "matrix-call-branch-transitive-v1-proposal"


def build(args):
    facts = FactSnapshot(args.facts, args.source_root, args.functions,
                         args.first_manifest, args.selected)
    calls = {}
    by_caller = defaultdict(list)
    unresolved = []
    for row in facts.rows("calls"):
        caller = facts.unit(row["col0"], row["col1"], row["col2"])
        if caller is None:
            continue
        callee = facts.unit(row["col3"], row["col4"], row["col5"])
        evidence = {"file": row["col6"], "start_line": int(row["col7"]),
                    "end_line": int(row["col8"])}
        if not (evidence["file"] == caller["file"] and
                caller["start_line"] <= evidence["start_line"] <= evidence["end_line"] <= caller["end_line"]):
            unresolved.append({"origin_id": caller["id"], "reason": "callsite_outside_caller",
                               "evidence": evidence})
            continue
        evidence["code"] = facts.span(evidence["file"], evidence["start_line"], evidence["end_line"])
        if callee is None:
            unresolved.append({"origin_id": caller["id"], "reason": "callee_outside_first_pass_inventory",
                               "callee": [row["col3"], row["col4"], row["col5"]],
                               "evidence": evidence})
            continue
        key = (caller["id"], callee["id"], evidence["file"], evidence["start_line"],
               evidence["end_line"])
        if key not in calls:
            calls[key] = {"caller": caller["id"], "callee": callee["id"],
                          "evidence": evidence}
            by_caller[caller["id"]].append(calls[key])
    for items in by_caller.values():
        items.sort(key=lambda item: (item["evidence"]["file"], item["evidence"]["start_line"],
                                     item["callee"]))

    unresolved_sites = defaultdict(list)
    for row in facts.rows("unresolved_calls"):
        caller = facts.unit(row["col0"], row["col1"], row["col2"])
        if caller is None:
            continue
        first, last = int(row["col4"]), int(row["col5"])
        if row["col3"] != caller["file"] or not caller["start_line"] <= first <= last <= caller["end_line"]:
            continue
        unresolved_sites[caller["id"]].append({"file": row["col3"], "start_line": first,
                                               "end_line": last,
                                               "code": facts.span(row["col3"], first, last)})

    candidates_by_id = {}
    origins = []
    for selected in facts.selected:
        origin = selected["unit_id"]
        roots = by_caller.get(origin, [])
        if not roots:
            unresolved.append({"origin_id": origin, "reason": "no_verified_direct_call_candidate"})
            continue
        for root in roots:
            members = {origin, root["callee"]}
            queue = [root["callee"]]
            while queue:
                current = queue.pop()
                for edge in by_caller.get(current, []):
                    if edge["callee"] not in members:
                        members.add(edge["callee"])
                        queue.append(edge["callee"])
            keys, functions = facts.function_payload(members)
            relations = []
            for caller in sorted(members):
                for edge in by_caller.get(caller, []):
                    if edge["callee"] in members:
                        relations.append({"kind": "direct_call", "from": keys[caller],
                                          "to": keys[edge["callee"]], "evidence": edge["evidence"]})
            relations.sort(key=lambda item: (item["evidence"]["file"],
                                             item["evidence"]["start_line"], item["from"], item["to"]))
            sites = []
            for member in sorted(members):
                sites.extend({"function": keys[member], **site}
                             for site in unresolved_sites.get(member, []))
                sites.extend({"function": keys[member], "reason": item["reason"],
                              **item["evidence"]}
                             for item in unresolved if item.get("origin_id") == member
                             and "evidence" in item)
            sites.sort(key=lambda item: (item["file"], item["start_line"], item["function"]))
            declarations = facts.declarations(members)
            state = {"operation": {"entry": keys[origin], "call_site": root["evidence"],
                                   "callee": keys[root["callee"]]},
                     "functions": functions, "supporting_declarations": declarations,
                     "supporting_macros": facts.macros(declarations),
                     "relations": relations, "unresolved_call_sites": sites}
            encoded = canonical(state)
            candidate_id = sha(facts.revision.encode() + b"\0" + encoded)
            if candidate_id not in candidates_by_id:
                candidates_by_id[candidate_id] = {
                    "candidate_id": candidate_id, "state_sha256": sha(encoded), "state": state}
            origins.append({"candidate_id": candidate_id, "origin_id": origin,
                            "member_ids": sorted(members),
                            "first_pass_score": selected["score"]})
    candidates = [candidates_by_id[key] for key in sorted(candidates_by_id)]
    write_view(args.output, "call", RULE, facts, candidates, origins, unresolved)
    print({"view": "call", "candidates": len(candidates),
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

#!/usr/bin/env python3
"""Make a lean Jev view of the five frozen CodeQL state-object candidates.

The source bodies are unchanged. CodeQL facts used to form the candidates stay
in the existing frozen run; the Jev view keeps only cross-function connections
and unresolved call locations that the function bodies cannot convey alone.
"""

import json

from pilot_codedb_state import ROOT, compact, read_jsonl, sha


BASE = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-25-v4"
OUTPUT = ROOT / "experiments/second-pass/runs/codedb-lean-pilot-2026-09-26-v1"


def build():
    if OUTPUT.exists():
        raise ValueError("frozen output already exists")
    base_manifest = json.loads((BASE / "manifest.json").read_text())
    originals = read_jsonl(BASE / "states.jsonl")
    if len(originals) != 5:
        raise ValueError("base candidate inventory changed")
    results = []
    comparison = []
    for old in originals:
        original_state = old["state"]
        if sha(compact(original_state)) != old["state_sha256"]:
            raise ValueError("base state hash mismatch")
        state = {
            "operation": original_state["operation"],
            "functions": original_state["functions"],
            "supporting_declarations": original_state["supporting_declarations"],
            "supporting_macros": original_state["supporting_macros"],
            "relations": original_state["relations"],
            "unresolved_call_sites": [
                {key: call[key] for key in ("function", "file", "start_line", "end_line")}
                for call in original_state["unresolved_calls"]
            ],
        }
        if len(state["functions"]) != len(original_state["functions"]):
            raise ValueError("a source body was omitted")
        encoded = compact(state)
        candidate_id = sha(base_manifest["source_revision"].encode() + b"\0" + encoded)
        results.append({"candidate_id": candidate_id, "state_sha256": sha(encoded),
                        "state_bytes": len(encoded), "state": state})
        comparison.append({"state_expression": state["operation"]["state_expression"],
                           "base_candidate_id": old["candidate_id"],
                           "new_candidate_id": candidate_id,
                           "base_state_bytes": old["state_bytes"],
                           "new_state_bytes": len(encoded),
                           "function_count": len(state["functions"])})
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "states.jsonl").write_text(
        "".join(compact(item).decode() + "\n" for item in results))
    (OUTPUT / "comparison-input.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "status": "lean_pilot_input_no_jev_calls",
        "source_revision": base_manifest["source_revision"],
        "base_states_sha256": sha((BASE / "states.jsonl").read_bytes()),
        "size_policy": "same full function bodies; no exclusions or truncation",
        "view_rule": "operation, complete functions, supporting declarations and macros, direct calls, unresolved call locations",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()

#!/usr/bin/env python3
"""Build one focused semantic augmentation of the frozen decoder candidate.

The evidence locations are verified against neutral CodeQL query outputs.
This is a case probe; selecting these observed paths is not an A input rule.
"""

import csv
import json
from pathlib import Path
import subprocess

from pilot_codedb_state import ROOT, SOURCE_ROOT, Sources, compact, sha


BASE = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-25-v4"
ENRICHED = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-26-v7"
OUTPUT = ROOT / "experiments/second-pass/runs/codedb-decoder-semantics-2026-09-26-v1"
FACTS = {
    "steps": Path("/tmp/sift-pilot-local-value-steps-2026-09-26.csv"),
    "guards": Path("/tmp/sift-pilot-guarded-effects-2026-09-26.csv"),
    "branches": Path("/tmp/sift-pilot-branch-effects-2026-09-26.csv"),
    "reachability": Path("/tmp/sift-pilot-local-reachability-probe2-2026-09-26.csv"),
    "indirect_arguments": Path("/tmp/sift-pilot-indirect-call-arguments-2026-09-26.csv"),
    "pointer_writes": Path("/tmp/sift-pilot-function-pointer-writes-2026-09-26.csv"),
}


def read_rows(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def flow(rows, from_line, to_line, from_column=None, to_column=None):
    return next((row for row in rows
                 if int(row["col1"]) == from_line and int(row["col5"]) == to_line
                 and (from_column is None or int(row["col2"]) == from_column)
                 and (to_column is None or int(row["col6"]) == to_column)
                 and row["kind"] == "exact_value"), None)


def build():
    if OUTPUT.exists():
        raise ValueError("frozen output already exists")
    base_revision = json.loads((BASE / "manifest.json").read_text())["source_revision"]
    current_revision = subprocess.check_output(
        ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    if current_revision != base_revision or subprocess.run(
        ["git", "-C", str(SOURCE_ROOT), "diff", "--quiet", "HEAD", "--"],
        check=False,
    ).returncode:
        raise ValueError("source snapshot does not match the frozen base")
    originals = [json.loads(line) for line in (BASE / "states.jsonl").read_text().splitlines()]
    old = next(row for row in originals
               if row["state"]["operation"]["state_expression"] == "p->decoder")
    if old["state_sha256"] != sha(compact(old["state"])):
        raise ValueError("base state hash mismatch")
    enriched = [json.loads(line) for line in (ENRICHED / "states.jsonl").read_text().splitlines()]
    support = next(row["state"] for row in enriched
                   if row["state"]["operation"]["state_expression"] == "p->decoder")
    facts = {name: read_rows(path) for name, path in FACTS.items()}
    source = Sources()

    checks = [
        ("585 destLenOrig to 606 assignment", flow(facts["reachability"], 585, 606, 23, 16)),
        ("632 destLen2 to 638 output", next((row for row in facts["steps"]
          if row["col2"] == "MixCoder_Code" and row["kind"] == "exact_value"
          and int(row["col4"]) == 632 and int(row["col8"]) == 638), None)),
        ("632 state to 649 override", flow(facts["reachability"], 632, 649, 5, 23)),
        ("649 override to 652 output", flow(facts["reachability"], 649, 652, 26, 18)),
    ]
    if any(value is None for _, value in checks):
        raise ValueError("a requested value relation is absent from CodeQL facts: "
                         + ", ".join(label for label, value in checks if value is None))
    value_relations = [
        {"kind": "possible_local_exact_value_flow", "from_line": start,
         "to_line": end,
         "from_code": source.lines_span("C/XzDec.c", start, start).strip(),
         "to_code": source.lines_span("C/XzDec.c", end, end).strip()}
        for start, end in ((585, 606), (632, 638), (632, 649), (649, 652))
    ]

    controls = []
    for condition_line, effect_line, kind, fact_name in (
        (597, 610, "guard_controls_true", "guards"),
        (637, 638, "guard_controls_true", "guards"),
        (648, 649, "then_branch_contains", "branches"),
    ):
        fact = next((row for row in facts[fact_name]
                     if row["col2"] == "MixCoder_Code"
                     and int(row["col3"]) == condition_line
                     and int(row["col7"]) == effect_line
                     and (fact_name != "guards" or row["testIsTrue"] == "true")
                     and (fact_name != "branches" or row["branchSide"] == "then")), None)
        if fact is None:
            raise ValueError(f"missing control evidence {condition_line}->{effect_line}")
        controls.append({"kind": kind, "condition_line": condition_line,
                         "condition_code": source.lines_span("C/XzDec.c", condition_line,
                                                              condition_line).strip(),
                         "effect_line": effect_line,
                         "effect_code": source.lines_span("C/XzDec.c", effect_line,
                                                           effect_line).strip()})

    call_arguments = []
    for call_line in (610, 731):
        rows = sorted((row for row in facts["indirect_arguments"]
                       if row["col2"] == "MixCoder_Code"
                       and int(row["col3"]) == call_line),
                      key=lambda row: int(row["index"]))
        if [int(row["index"]) for row in rows] != list(range(8)):
            raise ValueError("incomplete Code2 argument inventory")
        arguments = [{"index": int(row["index"]),
                      "code": source.expr("C/XzDec.c", *(
                          int(row[f"col{i}"]) for i in range(8, 12)))}
                     for row in rows]
        call_arguments.append({"call_line": call_line, "field": "IStateCoder.Code2",
                               "resolved_target": False, "arguments": arguments})
    if call_arguments[0]["arguments"][2]["code"] != "&destLen2":
        raise ValueError("expected address-passed output length not found")

    writes = {int(row["col3"]): row for row in facts["pointer_writes"]}
    if not {292, 455} <= writes.keys():
        raise ValueError("possible Code2 assignment missing")
    bindings = support["possible_indirect_bindings"]
    if {item["possible_target"] for item in bindings} != {
        "XzBcFilterState_Code2", "Lzma2State_Code2"
    }:
        raise ValueError("possible Code2 targets changed")
    target_bodies = [func for func in support["indirect_supporting_functions"]
                     if func["symbol"] in {item["possible_target"] for item in bindings}]
    if len(target_bodies) != 2:
        raise ValueError("target bodies missing")

    state = json.loads(json.dumps(old["state"]))
    state["semantic_evidence_scope"] = (
        "Observed MixCoder_Code output path only. CodeQL local flow is possible flow; "
        "branch containment does not prove reachability. Code2 target assignments "
        "are possible bindings, not proven runtime targets."
    )
    state["value_relations"] = value_relations
    state["controlled_effects"] = controls
    state["indirect_call_arguments"] = call_arguments
    state["possible_indirect_bindings"] = bindings
    state["possible_target_bodies"] = target_bodies
    encoded = compact(state)
    candidate_id = sha(old["candidate_id"].encode() + b"\0" + encoded)
    row = {"candidate_id": candidate_id, "state_sha256": sha(encoded),
           "state_bytes": len(encoded), "state": state}
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "states.jsonl").write_text(compact(row).decode() + "\n")
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "status": "focused_case_probe_input_no_jev_calls",
        "base_candidate_id": old["candidate_id"],
        "base_state_sha256": old["state_sha256"],
        "base_source_revision": base_revision,
        "fact_csv_sha256": {name: sha(path.read_bytes()) for name, path in FACTS.items()},
        "size_policy": "all original function bodies retained; evidence selected by observed output path, no byte threshold",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"base_state_bytes": old["state_bytes"],
                      "new_state_bytes": len(encoded),
                      "value_relations": len(value_relations),
                      "controlled_effects": len(controls),
                      "indirect_call_sites": len(call_arguments),
                      "possible_bindings": len(bindings),
                      "possible_target_bodies": len(target_bodies)}))


if __name__ == "__main__":
    build()

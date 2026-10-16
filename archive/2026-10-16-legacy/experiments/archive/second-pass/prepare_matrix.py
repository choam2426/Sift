#!/usr/bin/env python3
"""Freeze and verify four second-pass input views before any Jev request.

Input view directories contain manifest.json, states.jsonl, and origins.jsonl.
This command reads source and first-pass evidence, checks all candidate code,
and writes a request inventory. It contains no network or model call.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess


VIEWS = ("call", "value", "state", "effect")
FORBIDDEN_KEYS = {"case_id", "cve", "vulnerability_label", "first_pass_score",
                  "first_pass_rank", "patch", "fixed_revision", "score"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def no_forbidden_keys(value, where="state"):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"forbidden model-input key: {where}.{key}")
            no_forbidden_keys(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            no_forbidden_keys(child, f"{where}[{index}]")


def load_source(args):
    source_root = args.source_root.resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.run(["git", "-C", str(source_root), "diff", "--quiet", "HEAD", "--"],
                           check=False).returncode
    if dirty:
        raise ValueError("source has tracked changes")
    first_manifest = json.loads(args.first_manifest.read_text())
    if (first_manifest["source_revision"] != revision or
            first_manifest["functions_sha256"] != digest(args.functions.read_bytes())):
        raise ValueError("first-pass manifest does not match source/functions")
    functions = jsonl(args.functions)
    by_location = {(row["file"], row["start_line"], row["name"]): row
                   for row in functions}
    if len(by_location) != len(functions):
        raise ValueError("ambiguous function inventory")
    selected = jsonl(args.selected)
    selected_ids = {row["unit_id"] for row in selected}
    if len(selected_ids) != len(selected) or not selected_ids <= {row["id"] for row in functions}:
        raise ValueError("invalid first-pass selected inventory")
    for row in selected:
        if row.get("source_revision") != revision:
            raise ValueError("selected source revision mismatch")
    return revision, by_location, selected_ids


def check_function(function, by_location, source_root):
    key = (function["file"], function["start_line"], function["symbol"])
    unit = by_location.get(key)
    if unit is None or function["end_line"] != unit["end_line"] or function["code"] != unit["code"]:
        raise ValueError(f"function body differs from first-pass source: {key}")
    file_path = (source_root / function["file"]).resolve()
    if not file_path.is_relative_to(source_root) or not file_path.is_file():
        raise ValueError(f"source path outside snapshot: {function['file']}")
    lines = file_path.read_text(errors="replace").splitlines()
    original = "\n".join(lines[function["start_line"] - 1:function["end_line"]])
    if original != function["code"].replace("\r\n", "\n"):
        raise ValueError(f"function body differs from source file: {key}")
    return unit["id"]


def check_view(view, directory, revision, by_location, selected_ids, source_root):
    manifest_path = directory / "manifest.json"
    states_path = directory / "states.jsonl"
    origins_path = directory / "origins.jsonl"
    manifest = json.loads(manifest_path.read_text())
    if manifest["view"] != view or manifest["source_revision"] != revision:
        raise ValueError(f"{view}: view or source revision mismatch")
    if manifest.get("status") != "prepared_no_model_calls":
        raise ValueError(f"{view}: input is not a prepared view")
    if not manifest.get("rule_version") or not manifest.get("fact_snapshot_sha256"):
        raise ValueError(f"{view}: missing rule/fact version")
    rows = jsonl(states_path)
    if not rows:
        raise ValueError(f"{view}: no candidates")
    seen = set()
    for row in rows:
        candidate_id = row["candidate_id"]
        if candidate_id in seen:
            raise ValueError(f"{view}: duplicate candidate ID")
        seen.add(candidate_id)
        state = row["state"]
        no_forbidden_keys(state)
        encoded = canonical(state)
        if digest(encoded) != row["state_sha256"]:
            raise ValueError(f"{view}: state hash mismatch: {candidate_id}")
        functions = state.get("functions", [])
        if not functions or len({func["key"] for func in functions}) != len(functions):
            raise ValueError(f"{view}: empty or ambiguous functions: {candidate_id}")
        for function in functions:
            check_function(function, by_location, source_root)
        for declaration in [*state.get("supporting_declarations", []),
                            *state.get("supporting_macros", [])]:
            file_path = (source_root / declaration["file"]).resolve()
            if not file_path.is_relative_to(source_root) or not file_path.is_file():
                raise ValueError(f"{view}: declaration outside source snapshot")
            lines = file_path.read_text(errors="replace").splitlines()
            start, end = declaration["start_line"], declaration["end_line"]
            if not 1 <= start <= end <= len(lines) or "\n".join(lines[start - 1:end]) != declaration["code"].replace("\r\n", "\n"):
                raise ValueError(f"{view}: declaration differs from source")
        for relation in state.get("relations", []):
            if relation["from"] not in {f["key"] for f in functions} or relation["to"] not in {f["key"] for f in functions}:
                raise ValueError(f"{view}: relation endpoint outside candidate: {candidate_id}")
    origins = jsonl(origins_path)
    linked = defaultdict(set)
    for row in origins:
        if row["candidate_id"] not in seen or row["origin_id"] not in selected_ids:
            raise ValueError(f"{view}: invalid origin linkage")
        linked[row["candidate_id"]].add(row["origin_id"])
    if set(linked) != seen:
        raise ValueError(f"{view}: candidate without selected origin")
    return rows, {"manifest_sha256": digest(manifest_path.read_bytes()),
                  "states_sha256": digest(states_path.read_bytes()),
                  "origins_sha256": digest(origins_path.read_bytes()),
                  "candidate_count": len(rows), "origin_count": len({x["origin_id"] for x in origins}),
                  "fact_snapshot_sha256": manifest["fact_snapshot_sha256"],
                  "rule_version": manifest["rule_version"]}


def prepare(args):
    if args.output.exists():
        raise ValueError("output exists; choose a new run ID")
    if args.trials < 1:
        raise ValueError("trials must be positive")
    revision, by_location, selected_ids = load_source(args)
    facts_manifest = json.loads(args.facts_manifest.read_text())
    if (facts_manifest["status"] != "neutral_facts_no_model_calls" or
            facts_manifest["source_revision"] != revision):
        raise ValueError("CodeQL fact snapshot does not match source")
    facts_hash = digest(args.facts_manifest.read_bytes())
    questions = json.loads(args.questions.read_text())
    if (questions["status"] not in {"proposal_not_executed", "frozen_for_experiment"} or
            set(questions["questions"]) != {f"p{i}" for i in range(1, 6)}):
        raise ValueError("expected the five comparison questions")
    views = {}
    unique_requests = {}
    candidate_states = {}
    memberships = 0
    for view in VIEWS:
        directory = args.inputs / view
        rows, info = check_view(view, directory, revision, by_location, selected_ids,
                                args.source_root.resolve())
        if info["fact_snapshot_sha256"] != facts_hash:
            raise ValueError(f"{view}: fact snapshot hash mismatch")
        views[view] = info
        for row in rows:
            prior = candidate_states.setdefault(row["candidate_id"], row["state_sha256"])
            if prior != row["state_sha256"]:
                raise ValueError("candidate ID names different states across views")
            for question_id, prompt in sorted(questions["questions"].items()):
                question = {question_id: {"type": "noul", "instructions":
                            questions["common_instruction"] + " " + prompt}}
                question_hash = digest(canonical(question))
                for trial in range(1, args.trials + 1):
                    request_key = (row["state_sha256"], question_hash, trial)
                    request = unique_requests.setdefault(request_key, {
                        "state_sha256": row["state_sha256"], "question_id": question_id,
                        "question_sha256": question_hash, "trial": trial, "memberships": []})
                    request["memberships"].append({"view": view,
                                                    "candidate_id": row["candidate_id"]})
                    memberships += 1
    tasks = [unique_requests[key] for key in sorted(unique_requests)]
    manifest = {"status": "prepared_no_model_calls", "source_revision": revision,
                "model": questions["model"], "questions_sha256": digest(args.questions.read_bytes()),
                "first_manifest_sha256": digest(args.first_manifest.read_bytes()),
                "fact_manifest_sha256": facts_hash,
                "functions_sha256": digest(args.functions.read_bytes()),
                "selected_sha256": digest(args.selected.read_bytes()),
                "trials_per_candidate_question": args.trials, "views": views,
                "condition_count": 20, "condition_memberships": memberships,
                "unique_request_count": len(tasks)}
    args.output.mkdir(parents=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (args.output / "questions.json").write_bytes(args.questions.read_bytes())
    (args.output / "requests.jsonl").write_text("".join(canonical(task).decode() + "\n" for task in tasks))
    print(json.dumps({"status": manifest["status"], "views":
                      {key: value["candidate_count"] for key, value in views.items()},
                      "condition_memberships": memberships,
                      "unique_request_count": len(tasks)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--functions", type=Path, required=True)
    parser.add_argument("--first-manifest", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--facts-manifest", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True,
                        help="parent directory containing call/value/state/effect")
    parser.add_argument("--questions", type=Path, default=Path(__file__).with_name("matrix_questions.json"))
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args())

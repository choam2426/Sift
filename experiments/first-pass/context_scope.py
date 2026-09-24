#!/usr/bin/env python3
"""Compare identical Jev questions with function-only and local-context inputs."""

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import random

import contrast_holdout as base


RUN = base.HERE / "runs" / "context-scope"
QUESTION = "review_worth_plain"
REPEATS = (1, 2, 3)
PROFILES = ("function", "declarations")
CONTEXT_CHAR_LIMIT = 30000


def binding_names(statement):
    if isinstance(statement, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in statement.names}
    if isinstance(statement, ast.ImportFrom):
        return {alias.asname or alias.name for alias in statement.names}
    targets = []
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AnnAssign):
        targets = [statement.target]
    return {node.id for target in targets for node in ast.walk(target)
            if isinstance(node, ast.Name)}


def context_for(lines, tree, function, owner):
    """File-local declarations only; no other function body enters pass one."""
    snippets = []
    seen = {(function.lineno, function.end_lineno)}

    def add(label, node):
        if any(isinstance(child, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef))
               for child in ast.walk(node)):
            return
        key = (node.lineno, node.end_lineno)
        if key not in seen:
            seen.add(key)
            code = "".join(lines[node.lineno - 1:node.end_lineno]).rstrip()
            snippets.append(f"# {label}, lines {node.lineno}-{node.end_lineno}\n{code}\n")

    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    module_bindings = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            for name in binding_names(node):
                module_bindings[name] = node

    if owner is not None:
        header_end = owner.body[0].lineno - 1 if owner.body else owner.lineno
        header = "".join(lines[owner.lineno - 1:header_end]).rstrip()
        if header:
            snippets.append(f"# Enclosing class\n{header}\n")
        for node in owner.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                add("Class attribute", node)
        for base_expr in owner.bases:
            if isinstance(base_expr, ast.Name) and base_expr.id in classes:
                parent = classes[base_expr.id]
                parent_header_end = parent.body[0].lineno - 1 if parent.body else parent.lineno
                parent_header = "".join(lines[parent.lineno - 1:parent_header_end]).rstrip()
                if parent_header:
                    snippets.append(f"# Immediate base class\n{parent_header}\n")
                for node in parent.body:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        add("Base class attribute", node)

    used_names = {node.id for node in ast.walk(function)
                  if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    for name in sorted(used_names):
        if name in module_bindings:
            add("Referenced module binding " + name, module_bindings[name])

    result = ""
    omitted = 0
    for snippet in snippets:
        if len(result) + len(snippet) > CONTEXT_CHAR_LIMIT:
            omitted += 1
        else:
            result += snippet + "\n"
    return result.rstrip(), omitted


def prepared_units():
    original = base.units()
    by_id = {unit["id"]: unit for unit in original}
    prepared = {}
    for case in base.manifest():
        lines = base.source(case).splitlines(keepends=True)
        tree = ast.parse("".join(lines))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                candidates = [(node.name, node, None)]
            elif isinstance(node, ast.ClassDef):
                candidates = [(node.name + "." + child.name, child, node)
                              for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
            else:
                continue
            for name, function, owner in candidates:
                unit_id = case["id"] + ":" + name + ":" + str(function.lineno)
                unit = by_id[unit_id]
                context, omitted = context_for(lines, tree, function, owner)
                enhanced = dict(unit)
                enhanced["code"] = unit["code"] + ("\nRelated file-local context:\n" + context + "\n" if context else "")
                prepared[unit_id] = {
                    "function": unit, "declarations": enhanced,
                    "context_chars": len(context), "omitted": omitted,
                }
    if len(prepared) != len(original):
        raise ValueError("unit extraction changed")
    return prepared


def definition_hash():
    return base.digest(Path(__file__).read_bytes())


def run(prepared, workers):
    RUN.mkdir(parents=True, exist_ok=True)
    output = RUN / "responses.jsonl"
    existing = {}
    if output.exists():
        for line in output.read_text().splitlines():
            row = json.loads(line)
            key = (row["profile"], row["repeat"], row["unit_id"])
            unit = prepared[row["unit_id"]][row["profile"]]
            if (row["experiment_sha256"] != definition_hash()
                    or row["question_sha256"] != base.digest(json.dumps(base.QUESTIONS[QUESTION], sort_keys=True).encode())
                    or row["state_sha256"] != base.digest(base.state(unit).encode())
                    or row["requested_model"] != base.MODEL):
                raise ValueError("existing response incompatible with experiment")
            if row["status"] == "scored":
                existing[key] = row
    tasks = [(profile, repeat, unit_id) for profile in PROFILES for repeat in REPEATS
             for unit_id in prepared if (profile, repeat, unit_id) not in existing]
    random.Random(20260924).shuffle(tasks)
    secret = base.api_key()

    def worker(task):
        profile, repeat, unit_id = task
        unit = prepared[unit_id][profile]
        outcome = base.call(secret, QUESTION, unit)
        return {
            "unit_id": unit_id, "case": unit["case"], "profile": profile,
            "repeat": repeat, "question": QUESTION,
            "requested_model": base.MODEL,
            "experiment_sha256": definition_hash(),
            "question_sha256": base.digest(json.dumps(base.QUESTIONS[QUESTION], sort_keys=True).encode()),
            "state_sha256": base.digest(base.state(unit).encode()),
            "context_chars": prepared[unit_id]["context_chars"],
            "omitted_context_snippets": prepared[unit_id]["omitted"], **outcome,
        }

    with output.open("a") as sink, ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            sink.write(json.dumps(future.result()) + "\n")
            sink.flush()
            if i % 50 == 0 or i == len(tasks):
                print(f"{i}/{len(tasks)} requests finished", flush=True)


def report(prepared):
    output = RUN / "responses.jsonl"
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    scored = {(r["profile"], r["repeat"], r["unit_id"]): r for r in rows if r["status"] == "scored"}
    errors = [r for r in rows if r["status"] != "scored"]
    print("rows", len(rows), "scored", len(scored), "errors", len(errors))
    for fraction in (.1, .355):
        print("fraction", fraction)
        for profile in PROFILES:
            for repeat in REPEATS:
                hits = []
                ranks = {}
                for case in base.manifest():
                    pool = [entry[profile] for entry in prepared.values() if entry[profile]["case"] == case["id"]]
                    if any((profile, repeat, unit["id"]) not in scored for unit in pool):
                        raise ValueError("incomplete " + str((profile, repeat, case["id"])))
                    ranked = sorted(pool, key=lambda unit: (-scored[(profile, repeat, unit["id"])]["score"], unit["id"]))
                    rank = next(i for i, unit in enumerate(ranked, 1) if unit["target"])
                    ranks[case["id"]] = rank
                    if rank <= math.ceil(fraction * len(pool)):
                        hits.append(case["id"])
                print(profile, repeat, f"{len(hits)}/6", "ranks", ranks)
    for profile in PROFILES:
        values = [r for r in scored.values() if r["profile"] == profile]
        print(profile, "input tokens", sum(r["usage"]["input_tokens"] for r in values),
              "max", max(r["usage"]["input_tokens"] for r in values))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "report"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    prepared = prepared_units()
    if args.action == "prepare":
        print("units", len(prepared), "requests", len(prepared) * len(PROFILES) * len(REPEATS))
        print("with context", sum(bool(u["context_chars"]) for u in prepared.values()),
              "omitted snippets", sum(u["omitted"] for u in prepared.values()),
              "max context chars", max(u["context_chars"] for u in prepared.values()))
        for case in base.manifest():
            target = next(u for u in prepared.values() if u["function"]["case"] == case["id"] and u["function"]["target"])
            print(case["id"], "target context chars", target["context_chars"],
                  "omitted", target["omitted"])
    elif args.action == "run":
        run(prepared, args.workers)
    else:
        report(prepared)


if __name__ == "__main__":
    main()

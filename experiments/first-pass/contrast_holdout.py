#!/usr/bin/env python3
"""Reproducible, whole-file Jev first-pass comparison on unseen vulnerabilities."""

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import random
import threading
import time
import urllib.error
import urllib.request


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = HERE / "runs" / "contrast-holdout"
MODEL = "jev-1.13.0"
API = "https://api.typesafe.ai/v1/systemone"
QUESTIONS = {
    "contrastive": {
        "type": "noul",
        "instructions": "Would a focused review of this function resolve a concrete, security-relevant correctness question? Compare the strongest explanation under which the shown behavior is correct with the strongest code-grounded explanation under which it is incorrect. Judge the value of checking what separates those explanations.",
        "criteria": {
            "true": "The shown code supports a specific consequential behavior, a specific condition on which its correctness depends, and a focused check that could distinguish correct from incorrect behavior. Local evidence may already resolve the question, or a particular related contract may resolve it. An external contract can qualify without a locally visible defect, but its relevance must be grounded in the shown behavior.",
            "false": "The concern consists only of complexity, an API or function name, generic missing context, or an imagined failure of otherwise ordinary callers. No specific correctness condition and discriminating check can be identified, or the shown checks already establish the condition for the relevant behavior. Do not accumulate weak concerns merely because a function is long.",
        },
    },
    "review_worth_plain": {
        "type": "noul",
        "instructions": "Is this function worth a security researcher's time to inspect further for bugs?",
    },
    "concrete_suspicion": {
        "type": "noul",
        "instructions": "The shown code provides a concrete reason to suspect a security-relevant implementation error.",
        "criteria": {
            "true": "A specific operation, condition, check, or unchecked assumption in the shown code supports suspicion of an implementation error with possible security impact; related code may be needed to confirm it.",
            "false": "No specific behavior in the shown code supports such suspicion. Complexity, security relevance, or sensitive APIs alone do not count.",
        },
    },
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    return json.loads((HERE / "contrast_holdout.json").read_text())


def source(case):
    cache = RUN / "sources" / (case["id"] + ".py")
    if cache.exists():
        data = cache.read_bytes()
    else:
        with urllib.request.urlopen(case["source"], timeout=30) as response:
            data = response.read()
        if digest(data) == case["sha256"]:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
    if digest(data) != case["sha256"]:
        raise ValueError("source hash mismatch: " + case["id"])
    return data.decode("utf-8")


def units():
    result = []
    for case in manifest():
        lines = source(case).splitlines(keepends=True)
        tree = ast.parse("".join(lines))
        pool = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pool.append((node.name, node))
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        pool.append((node.name + "." + child.name, child))
        if sum(name == case["target"] for name, _ in pool) != 1:
            raise ValueError("missing or ambiguous target: " + case["id"])
        for name, node in pool:
            code = "".join(lines[node.lineno - 1:node.end_lineno])
            result.append({
                "id": case["id"] + ":" + name + ":" + str(node.lineno),
                "case": case["id"],
                "name": name,
                "target": name == case["target"],
                "code": code,
                "chars": len(code),
                "line": node.lineno,
            })
    return result


def api_key():
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    raise RuntimeError("TYPESAFE_API_KEY is missing")


def state(unit):
    return f"Function: {unit['name']}\nCode:\n{unit['code']}"


def call(secret, question, unit):
    body = json.dumps({
        "model": MODEL,
        "state": state(unit),
        "questions": {question: QUESTIONS[question]},
    }).encode()
    request = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + secret,
        "Content-Type": "application/json",
    })
    for attempt in range(5):
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.load(response)
            answer = data["answers"][question]["noul"]
            if not isinstance(answer, (int, float)) or not 0 <= answer <= 1:
                raise ValueError("invalid noul answer")
            return {"status": "scored", "score": answer, "model": data["model"],
                    "usage": data.get("usage"), "ms": round(1000 * (time.monotonic() - start))}
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504, 529) or attempt == 4:
                return {"status": "error", "error": "HTTP " + str(error.code)}
        except (TimeoutError, urllib.error.URLError):
            if attempt == 4:
                return {"status": "error", "error": "timeout or connection failure"}
        time.sleep(min(2 ** attempt, 8))
    raise AssertionError("unreachable")


def run(all_units, workers):
    RUN.mkdir(parents=True, exist_ok=True)
    output = RUN / "responses.jsonl"
    unit_map = {unit["id"]: unit for unit in all_units}
    manifest_hash = digest((HERE / "contrast_holdout.json").read_bytes())
    done = set()
    if output.exists():
        for line in output.read_text().splitlines():
            row = json.loads(line)
            unit = unit_map.get(row["unit_id"])
            if (unit is None or row["manifest_sha256"] != manifest_hash
                    or row["question_sha256"] != digest(json.dumps(QUESTIONS[row["question"]], sort_keys=True).encode())
                    or row["state_sha256"] != digest(state(unit).encode())
                    or row["requested_model"] != MODEL):
                raise ValueError("existing response incompatible with frozen experiment")
            if row["status"] == "scored":
                done.add((row["question"], row["repeat"], row["unit_id"]))
    tasks = [(q, repeat, unit) for q in QUESTIONS for repeat in (1, 2, 3)
             for unit in all_units if (q, repeat, unit["id"]) not in done]
    secret = api_key()
    lock = threading.Lock()
    completed = 0

    def worker(task):
        question, repeat, unit = task
        result = call(secret, question, unit)
        return {
            "unit_id": unit["id"], "case": unit["case"], "question": question,
            "repeat": repeat, "requested_model": MODEL,
            "manifest_sha256": manifest_hash,
            "question_sha256": digest(json.dumps(QUESTIONS[question], sort_keys=True).encode()),
            "state_sha256": digest(state(unit).encode()), **result,
        }

    with output.open("a") as sink, ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, task) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            with lock:
                sink.write(json.dumps(row) + "\n")
                sink.flush()
                completed += 1
                if completed % 50 == 0 or completed == len(tasks):
                    print(f"{completed}/{len(tasks)} requests finished", flush=True)


def report(all_units):
    output = RUN / "responses.jsonl"
    if not output.exists():
        raise ValueError("no responses")
    scored = {}
    errors = []
    for line in output.read_text().splitlines():
        row = json.loads(line)
        key = (row["question"], row["repeat"], row["unit_id"])
        if row["status"] == "scored":
            scored[key] = row["score"]
        else:
            errors.append(key)
    grouped = {case["id"]: [u for u in all_units if u["case"] == case["id"]] for case in manifest()}
    print("pool sizes", {case: len(pool) for case, pool in grouped.items()})
    print("scored", len(scored), "errors", len(errors))
    for fraction in (0.10, 0.355):
        print("fraction", fraction)
        for question in QUESTIONS:
            for repeat in (1, 2, 3):
                hits = []
                ranks = {}
                for case, pool in grouped.items():
                    if any((question, repeat, u["id"]) not in scored for u in pool):
                        raise ValueError(f"incomplete: {question} {repeat} {case}")
                    ranked = sorted(pool, key=lambda u: (-scored[(question, repeat, u["id"])], u["id"]))
                    rank = next(i for i, u in enumerate(ranked, 1) if u["target"])
                    ranks[case] = rank
                    if rank <= math.ceil(fraction * len(pool)):
                        hits.append(case)
                print(question, repeat, f"{len(hits)}/6", "hits", hits, "ranks", ranks)
        hits = []
        for case, pool in grouped.items():
            ranked = sorted(pool, key=lambda u: (-u["chars"], u["id"]))
            rank = next(i for i, u in enumerate(ranked, 1) if u["target"])
            if rank <= math.ceil(fraction * len(pool)):
                hits.append(case)
        print("length", f"{len(hits)}/6", hits)
        rng = random.Random(20260923)
        random_hits = []
        for _ in range(1000):
            count = 0
            for pool in grouped.values():
                selected = rng.sample(pool, math.ceil(fraction * len(pool)))
                count += any(u["target"] for u in selected)
            random_hits.append(count)
        print("random", "mean", sum(random_hits) / len(random_hits),
              "range", (min(random_hits), max(random_hits)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "report"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    all_units = units()
    if args.action == "prepare":
        for case in manifest():
            pool = [u for u in all_units if u["case"] == case["id"]]
            target = next(u for u in pool if u["target"])
            print(case["id"], len(pool), "top10", math.ceil(.1 * len(pool)),
                  "top35.5", math.ceil(.355 * len(pool)), "target line", target["line"])
        print("total", len(all_units), "requests", len(all_units) * len(QUESTIONS) * 3)
    elif args.action == "run":
        run(all_units, args.workers)
    else:
        report(all_units)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Score every extracted function in one pinned source snapshot with Jev."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(__file__).resolve().parent / "runs"
API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
QUESTION_NAME = "review_worth_plain"
QUESTION = {
    "type": "noul",
    "instructions": "Is this function worth a security researcher's time to inspect further for bugs?",
}
QUESTIONS = {QUESTION_NAME: QUESTION}
PROFILE = "function-body-v1"
PROFILES = (PROFILE, "code-only-v1")
THRESHOLD = 0.60


def digest(data):
    return hashlib.sha256(data).hexdigest()


def state(unit, profile=PROFILE):
    if profile == "code-only-v1":
        return unit["code"]
    if profile != PROFILE:
        raise ValueError("unknown input profile: " + profile)
    # Match the input used by compare_questions.py for the adopted 7-Zip sample.
    header = f"{unit['qualified']} {unit.get('params', '')}".rstrip()
    return f"Function: {header}\nCode:\n{unit['code']}"


def source_revision(source_root):
    return subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()


def prepare(functions_path, source_root, profile=PROFILE):
    rows = [json.loads(line) for line in functions_path.read_text().splitlines() if line]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("function list is empty or has duplicate IDs")
    for row in rows:
        source = (source_root / row["file"]).read_bytes().decode(
            "utf-8", errors="replace"
        ).splitlines(keepends=True)
        actual = "".join(source[row["start_line"] - 1:row["end_line"]]).rstrip("\r\n")
        if actual != row["code"]:
            raise ValueError("function differs from source: " + row["id"])
    dirty = subprocess.run(
        ["git", "-C", str(source_root), "diff", "--quiet", "HEAD", "--"],
        check=False,
    )
    if dirty.returncode != 0:
        raise ValueError("tracked source changes would make the revision ambiguous")
    manifest = {
        "source_revision": source_revision(source_root),
        "source_root": str(source_root.resolve()),
        "functions_sha256": digest(functions_path.read_bytes()),
        "function_count": len(rows),
        "input_profile": profile,
        "requested_model": MODEL,
        "question": QUESTIONS,
        "question_sha256": digest(json.dumps(QUESTIONS, sort_keys=True).encode()),
        "threshold": THRESHOLD,
    }
    return rows, manifest


def api_key():
    secret = os.environ.get("TYPESAFE_API_KEY")
    if secret:
        return secret
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    raise RuntimeError("TYPESAFE_API_KEY is missing")


def call(secret, input_state):
    body = json.dumps({"model": MODEL, "state": input_state, "questions": QUESTIONS}).encode()
    request = urllib.request.Request(API, data=body, headers={
        "Authorization": "Bearer " + secret,
        "Content-Type": "application/json",
    })
    started = time.monotonic()
    retry_errors = []
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = json.load(response)
            score = raw["answers"][QUESTION_NAME]["noul"]
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
                raise ValueError("invalid noul answer")
            return {
                "status": "scored", "score": score, "model": raw["model"],
                "usage": raw.get("usage"), "response": raw,
                "ms": round(1000 * (time.monotonic() - started)),
                "attempts": attempt, "retry_errors": retry_errors,
            }
        except urllib.error.HTTPError as error:
            retry_errors.append("HTTP " + str(error.code))
            if error.code not in (408, 429, 500, 502, 503, 504, 529) or attempt == 5:
                return {"status": "error", "error": retry_errors[-1],
                        "attempts": attempt, "retry_errors": retry_errors,
                        "ms": round(1000 * (time.monotonic() - started))}
        except (TimeoutError, urllib.error.URLError):
            retry_errors.append("timeout or connection failure")
            if attempt == 5:
                return {"status": "error", "error": retry_errors[-1],
                        "attempts": attempt, "retry_errors": retry_errors,
                        "ms": round(1000 * (time.monotonic() - started))}
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "error": "invalid API response",
                    "attempts": attempt, "retry_errors": retry_errors,
                    "ms": round(1000 * (time.monotonic() - started))}
        time.sleep(min(2 ** (attempt - 1), 8))
    raise AssertionError("unreachable")


def output_dir(run_id):
    if not run_id or Path(run_id).name != run_id:
        raise ValueError("run ID must be a single directory name")
    return RUNS / run_id


def run(rows, manifest, run_id, workers):
    directory = output_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("existing run has a different input manifest")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    output = directory / "responses.jsonl"
    profile = manifest["input_profile"]
    units = {row["id"]: row for row in rows}
    done = set()
    if output.exists():
        for line in output.read_text().splitlines():
            record = json.loads(line)
            unit = units.get(record["unit_id"])
            if (unit is None or record["state_sha256"] != digest(state(unit, profile).encode())
                    or record["question_sha256"] != manifest["question_sha256"]
                    or record["requested_model"] != MODEL
                    or record["input_profile"] != profile):
                raise ValueError("existing response has a different input")
            if record["status"] == "scored":
                done.add(record["unit_id"])
    pending = [row for row in rows if row["id"] not in done]
    if not pending:
        print("all functions already scored")
        return
    secret = api_key()

    def worker(unit):
        input_state = state(unit, profile)
        return {
            "unit_id": unit["id"], "input_profile": profile,
            "state_sha256": digest(input_state.encode()),
            "question_sha256": manifest["question_sha256"],
            "requested_model": MODEL,
            **call(secret, input_state),
        }

    with output.open("a") as sink, ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, unit) for unit in pending]
        for index, future in enumerate(as_completed(futures), 1):
            record = future.result()
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            sink.flush()
            if index % 50 == 0 or index == len(pending):
                print(f"{index}/{len(pending)} requests finished", flush=True)


def report(rows, manifest, run_id):
    directory = output_dir(run_id)
    if json.loads((directory / "manifest.json").read_text()) != manifest:
        raise ValueError("run manifest does not match current input")
    units = {row["id"]: row for row in rows}
    profile = manifest["input_profile"]
    latest = {}
    for line in (directory / "responses.jsonl").read_text().splitlines():
        record = json.loads(line)
        unit = units.get(record["unit_id"])
        if (unit is None or record["state_sha256"] != digest(state(unit, profile).encode())
                or record["question_sha256"] != manifest["question_sha256"]
                or record["requested_model"] != MODEL
                or record["input_profile"] != profile):
            raise ValueError("response does not match current input")
        latest[record["unit_id"]] = record
    scored = {key: value for key, value in latest.items() if value["status"] == "scored"}
    errors = {key: value for key, value in latest.items() if value["status"] != "scored"}
    missing = len(rows) - len(latest)
    print("functions", len(rows), "scored", len(scored), "errors", len(errors), "missing", missing)
    print("actual models", sorted({row["model"] for row in scored.values()}))
    print("input tokens", sum((row.get("usage") or {}).get("input_tokens", 0) for row in scored.values()))
    if errors or missing or len(scored) != len(rows):
        raise ValueError("incomplete first-pass evaluation; rerun before extraction")
    if {row["model"] for row in scored.values()} != {MODEL}:
        raise ValueError("actual model differs from the version used to calibrate the threshold")
    selected = sorted(
        (row for row in rows if scored[row["id"]]["score"] >= THRESHOLD),
        key=lambda row: (-scored[row["id"]]["score"], row["id"]),
    )
    records = [
        {"unit_id": row["id"], "score": scored[row["id"]]["score"],
         "source_revision": manifest["source_revision"], "input_profile": profile,
         "question_sha256": manifest["question_sha256"], "model": MODEL}
        for row in selected
    ]
    (directory / "selected.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    print("selected", len(records), "fraction", round(len(records) / len(rows), 4))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "report"))
    parser.add_argument("--functions", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=PROFILES, default=PROFILE)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    rows, manifest = prepare(args.functions, args.source_root, args.profile)
    if args.action == "prepare":
        print("functions", len(rows), "revision", manifest["source_revision"])
        print("question_sha256", manifest["question_sha256"])
        print("largest state bytes", max(len(state(row, args.profile).encode()) for row in rows))
    elif args.action == "run":
        run(rows, manifest, args.run_id, args.workers)
    else:
        report(rows, manifest, args.run_id)


if __name__ == "__main__":
    main()

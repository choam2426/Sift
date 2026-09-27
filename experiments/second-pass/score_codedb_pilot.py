#!/usr/bin/env python3
"""Score five frozen CodeQL-DB fact pilot states with one Jev trial each."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = ROOT / "experiments/second-pass/runs/codedb-state-pilot-2026-09-25-v4"
MODEL = "jev-1.13.0"
API = "https://api.typesafe.ai/v1/systemone"
QUESTION_NAME = "has_security_vulnerability"
QUESTIONS = {
    QUESTION_NAME: {
        "type": "noul",
        "instructions": (
            "Based only on the supplied code and relations, does the operation involving "
            "the stated state object contain a concrete security vulnerability? "
            "A positive assessment requires a specific failure mechanism with security "
            "impact supported by the supplied code. Complexity or risky API use alone "
            "is insufficient. Treat unresolved calls or missing context as uncertainty."
        ),
    }
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def api_key():
    secret = os.environ.get("TYPESAFE_API_KEY")
    if secret:
        return secret
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    raise RuntimeError("TYPESAFE_API_KEY is missing")


def score(secret, state, questions=QUESTIONS, question_name=QUESTION_NAME):
    payload = json.dumps({"model": MODEL, "state": state, "questions": questions},
                         ensure_ascii=False).encode()
    request = urllib.request.Request(API, data=payload, headers={
        "Authorization": "Bearer " + secret,
        "Content-Type": "application/json",
    })
    started = time.monotonic()
    attempts = []
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = json.load(response)
            answer = raw["answers"][question_name]["noul"]
            actual_model = raw["model"]
            if (isinstance(answer, bool) or not isinstance(answer, (int, float))
                    or not math.isfinite(answer) or not 0 <= answer <= 1
                    or actual_model != MODEL):
                raise ValueError("invalid answer or actual model")
            return {"status": "scored", "score": answer, "actual_model": actual_model,
                    "raw_response": raw, "usage": raw.get("usage"),
                    "http_attempts": attempt,
                    "elapsed_ms": round(1000 * (time.monotonic() - started)),
                    "retry_errors": attempts}
        except urllib.error.HTTPError as error:
            attempts.append({"kind": "http", "status": error.code})
            if error.code == 400 and b"max_tokens_exceeded" in error.read(4096):
                return {"status": "unscored", "error_kind": "max_tokens_exceeded",
                        "http_status": error.code, "http_attempts": attempt,
                        "elapsed_ms": round(1000 * (time.monotonic() - started)),
                        "retry_errors": attempts}
            if error.code not in (408, 429, 500, 502, 503, 504, 529) or attempt == 5:
                return {"status": "error", "error_kind": "http", "http_status": error.code,
                        "http_attempts": attempt,
                        "elapsed_ms": round(1000 * (time.monotonic() - started)),
                        "retry_errors": attempts}
        except (TimeoutError, urllib.error.URLError):
            attempts.append({"kind": "transport"})
            if attempt == 5:
                return {"status": "error", "error_kind": "transport",
                        "http_attempts": attempt,
                        "elapsed_ms": round(1000 * (time.monotonic() - started)),
                        "retry_errors": attempts}
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "error_kind": "invalid_response",
                    "http_attempts": attempt,
                    "elapsed_ms": round(1000 * (time.monotonic() - started)),
                    "retry_errors": attempts}
        time.sleep(min(2 ** (attempt - 1), 8))
    raise AssertionError("unreachable")


def run(run_dir=DEFAULT_RUN):
    if run_dir.parent.resolve() != (ROOT / "experiments/second-pass/runs").resolve():
        raise ValueError("run directory must be an experiment run")
    states_path = run_dir / "states.jsonl"
    rows = [json.loads(line) for line in states_path.read_text().splitlines() if line]
    if not rows or len({row["candidate_id"] for row in rows}) != len(rows):
        raise ValueError("pilot state inventory changed")
    for row in rows:
        if sha(compact(row["state"])) != row["state_sha256"]:
            raise ValueError("state hash mismatch")
    manifest = {"status": "pilot_not_baseline", "requested_model": MODEL,
                "question": QUESTIONS, "question_sha256": sha(compact(QUESTIONS)),
                "states_sha256": sha(states_path.read_bytes()),
                "candidate_ids": sorted(row["candidate_id"] for row in rows),
                "trials_per_candidate": 1}
    manifest_path = run_dir / "score-manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("score manifest differs from frozen input")
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    responses_path = run_dir / "responses.jsonl"
    done = set()
    if responses_path.exists():
        for line in responses_path.read_text().splitlines():
            record = json.loads(line)
            input_row = next((row for row in rows if row["candidate_id"] == record["candidate_id"]), None)
            if (input_row is None or record["state_sha256"] != input_row["state_sha256"]
                    or record["question_sha256"] != manifest["question_sha256"]
                    or record["requested_model"] != MODEL or record["trial"] != 1):
                raise ValueError("existing response does not match input")
            if record["status"] == "scored":
                done.add(record["candidate_id"])
    pending = [row for row in rows if row["candidate_id"] not in done]
    if not pending:
        print("all pilot candidates already scored")
        return
    secret = api_key()
    with responses_path.open("a") as output:
        for index, row in enumerate(pending, 1):
            result = score(secret, row["state"])
            record = {"candidate_id": row["candidate_id"], "trial": 1,
                      "state_sha256": row["state_sha256"],
                      "question_sha256": manifest["question_sha256"],
                      "requested_model": MODEL, **result}
            output.write(compact(record).decode() + "\n")
            output.flush()
            print(f"{index}/{len(pending)} {row['state']['operation']['state_expression']} "
                  f"{result['status']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    run(parser.parse_args().run_dir)

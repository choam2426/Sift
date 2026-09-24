#!/usr/bin/env python3
"""Compare Jev questions on pinned vulnerable, patched, and control functions."""

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(__file__).resolve().parent / "runs"
MODEL = "jev-1.13.0"
API = "https://api.typesafe.ai/v1/systemone"
QUESTION_SET = os.environ.get("SIFT_QUESTION_SET", "isolated-bug_worth_single")
SAMPLE_SET = os.environ.get("SIFT_SAMPLE_SET", "pilot")
if SAMPLE_SET not in ("pilot", "expanded"):
    raise ValueError(f"unknown sample set: {SAMPLE_SET}")
BUG_KEYS = (("C/XzDec.c", "MixCoder_Code"), ("C/XzDec.c", "XzUnpacker_Code"))
CONTROL_KEYS = (
    ("C/7zCrc.c", "CrcCalc"),
    ("C/7zAlloc.c", "SzFree"),
    ("C/Threads.c", "ThreadNextGroup_Init"),
    ("C/7zArcIn.c", "TestSignatureCandidate"),
    ("C/XzIn.c", "Xz_ReadHeader"),
    ("C/7zFile.c", "FileSeqInStream_Read"),
)
CONCRETE_SUSPICION_CRITERIA = {
    "true": "A specific operation, condition, check, or unchecked assumption in the shown code supports suspicion of an implementation error with possible security impact; related code may be needed to confirm it.",
    "false": "No specific behavior in the shown code supports such suspicion. Complexity, security relevance, or sensitive APIs alone do not count.",
}
QUESTIONS = {
    "combined": {
        "type": "noul",
        "instructions": "Should this function be selected for further security investigation? Judge only from the code shown.",
        "criteria": {
            "true": "Select when a concrete operation or decision could lead to a security-relevant failure if an assumption about input, bounds, state, permissions, ownership, or error handling is wrong. The related code may be needed to check that assumption. A confirmed bug is not required.",
            "false": "Do not select only because the function is long, complex, has a security-related name, or calls a potentially dangerous API. Select false when the shown behavior has no concrete security-relevant failure mechanism or unresolved safety condition.",
        },
    },
    "operation": {
        "type": "noul",
        "instructions": "Does this function perform an operation or decision whose incorrect behavior could have a security impact?",
        "criteria": {
            "true": "Examples include handling untrusted data, deciding access or state changes, managing memory bounds, or owning resources. A bug need not be visible.",
            "false": "Routine work with no security-relevant boundary or resource operation. A security-related name alone is insufficient.",
        },
    },
    "assumption": {
        "type": "noul",
        "instructions": "Does the shown code leave a concrete security-relevant condition or assumption that deserves checking in related code?",
        "criteria": {
            "true": "There is a plausible condition about input, bounds, state, permissions, ownership, or error handling that could cause unsafe behavior if it does not hold.",
            "false": "No concrete unresolved safety or security condition is visible; length, complexity, or a risky API name alone does not count.",
        },
    },
    "bug_likely_plain": {
        "type": "noul",
        "instructions": "Is this function likely to contain a security-relevant implementation bug?",
    },
    "bug_likely_criteria": {
        "type": "noul",
        "instructions": "Is this function likely to contain a security-relevant implementation bug, based on the code shown?",
        "criteria": {
            "true": "The shown code gives concrete evidence of an incorrect condition, unchecked bound, unsafe state transition, invalid ownership assumption, or security check failure that could cause unsafe behavior.",
            "false": "No concrete defect is visible. Complexity, a dangerous operation, or missing caller context alone does not establish a likely bug.",
        },
    },
    "review_worth_plain": {
        "type": "noul",
        "instructions": "Is this function worth a security researcher's time to inspect further for bugs?",
    },
    "bug_visible": {
        "type": "noul",
        "instructions": "Does the code shown contain concrete evidence of a security-relevant implementation bug?",
    },
    "bug_if_context": {
        "type": "noul",
        "instructions": "Could this function cause a security-relevant bug if a condition that must be checked by its callers or related code does not hold?",
    },
    "bug_worth_single": {
        "type": "noul",
        "instructions": "Is this function likely enough to contain or enable a security-relevant implementation bug that a researcher should inspect its related code?",
        "criteria": {
            "true": "The shown code gives a specific reason to suspect a mistake or unchecked assumption with possible security impact, even if related code is needed to confirm it.",
            "false": "The function is only complex or security-sensitive, with no specific reason in the shown code to suspect incorrect behavior. Its related code is unlikely to reveal a bug from this lead.",
        },
    },
    "concrete_suspicion_statement": {
        "type": "noul",
        "instructions": "The shown code provides a concrete reason to suspect a security-relevant implementation error.",
        "criteria": CONCRETE_SUSPICION_CRITERIA,
    },
    "concrete_suspicion_question": {
        "type": "noul",
        "instructions": "Does the shown code provide a concrete reason to suspect a security-relevant implementation error?",
        "criteria": CONCRETE_SUSPICION_CRITERIA,
    },
}
QUESTION_NAMES = {f"isolated-{name}": name for name in QUESTIONS}
if QUESTION_SET not in QUESTION_NAMES:
    raise ValueError(f"unknown single-question set: {QUESTION_SET}")
name = QUESTION_NAMES[QUESTION_SET]
QUESTIONS = {name: QUESTIONS[name]}


def functions(name):
    with (ROOT / "data" / name).open() as source:
        return [json.loads(line) for line in source]


def key(fn):
    return fn["file"], fn["name"]


def sample():
    vulnerable = functions("7zip.c.functions.jsonl")
    patched = {key(fn): fn for fn in functions("7zip-latest.c.functions.jsonl")}
    by_key = {key(fn): fn for fn in vulnerable}
    picked = [(by_key[item], "known_bug") for item in BUG_KEYS]
    eligible = [fn for fn in vulnerable if key(fn) not in BUG_KEYS]
    for fn in sorted(eligible, key=lambda fn: (-len(fn["code"]), fn["id"]))[:4]:
        picked.append((fn, "long"))
    bands = ((0, 500), (500, 2000), (2000, 5000), (5000, 8000))
    for low, high in bands:
        band = [fn for fn in eligible if low <= len(fn["code"]) < high]
        band.sort(key=lambda fn: hashlib.sha256(fn["id"].encode()).hexdigest())
        picked.append((band[0], "length_band"))
    for item in BUG_KEYS:
        picked.append((patched[item], "patched_counterpart"))
    for item in CONTROL_KEYS:
        picked.append((by_key[item], "reviewed_control"))
    sources = {}
    sample_files = ["extra_samples.json"]
    if SAMPLE_SET == "expanded":
        sample_files.append("expanded_samples.json")
    extras = [
        item
        for filename in sample_files
        for item in json.loads((Path(__file__).resolve().parent / filename).read_text())
    ]
    for item in extras:
        url = item["url"]
        if url not in sources:
            with urllib.request.urlopen(url, timeout=30) as response:
                sources[url] = response.read().decode().splitlines()
        code = "\n".join(sources[url][item["start_line"] - 1 : item["end_line"]]) + "\n"
        if hashlib.sha256(code.encode()).hexdigest() != item["sha256"]:
            raise ValueError(f"source changed: {item['unit_id']}")
        picked.append(({
            "id": item["unit_id"],
            "name": item["name"],
            "qualified": item["name"],
            "params": "",
            "code": code,
        }, item["group"]))
    return picked


def api_key():
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    raise RuntimeError("TYPESAFE_API_KEY is missing")


def call(secret, state):
    body = json.dumps({"model": MODEL, "state": state, "questions": QUESTIONS}).encode()
    request = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
    )
    for attempt in range(3):
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response), round((time.monotonic() - start) * 1000)
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504, 529) or attempt == 2:
                raise RuntimeError(f"HTTP {error.code}") from None
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise RuntimeError("request timeout or connection failure") from None
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else QUESTION_SET
    out_dir = RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "responses.jsonl"
    done = {}
    question_hash = hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode()).hexdigest()
    if output.exists():
        with output.open() as previous:
            for line in previous:
                row = json.loads(line)
                if row.get("question_sha256") != question_hash or row.get("requested_model") != MODEL:
                    raise ValueError("existing run has a different question set or model")
                if row.get("sample_set", "pilot") != SAMPLE_SET:
                    raise ValueError("existing run has a different sample set")
                if row["status"] == "scored":
                    done[row["unit_id"]] = row
    selected = sample()
    manifest = [{"unit_id": fn["id"], "group": group, "code_chars": len(fn["code"])} for fn, group in selected]
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    states = [
        {"unit_id": fn["id"], "state": f"Function: {fn['qualified']} {fn.get('params', '')}\nCode:\n{fn['code']}"}
        for fn, _ in selected
    ]
    (out_dir / "states.jsonl").write_text("".join(json.dumps(row) + "\n" for row in states))
    state_by_id = {row["unit_id"]: row["state"] for row in states}
    for unit_id, row in done.items():
        state = state_by_id.get(unit_id)
        if state is None or row.get("state_sha256") != hashlib.sha256(state.encode()).hexdigest():
            raise ValueError(f"existing run has a different input: {unit_id}")
    secret = api_key()
    with output.open("a") as sink:
        for index, (fn, group) in enumerate(selected, 1):
            if fn["id"] in done:
                continue
            state = state_by_id[fn["id"]]
            row = {
                "unit_id": fn["id"],
                "group": group,
                "input_profile": "function-body-v1",
                "state_sha256": hashlib.sha256(state.encode()).hexdigest(),
                "question_set": QUESTION_SET,
                "sample_set": SAMPLE_SET,
                "question_sha256": question_hash,
                "requested_model": MODEL,
            }
            try:
                response, elapsed = call(secret, state)
                answers = response["answers"]
                row.update({
                    "status": "scored",
                    "model": response["model"],
                    "answers": {name: answers[name] for name in QUESTIONS},
                    "usage": response.get("usage"),
                    "ms": elapsed,
                })
            except RuntimeError as error:
                row.update({"status": "error", "error": str(error)})
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            print(f"{index}/{len(selected)} {fn['name']} {row['status']}", flush=True)
    print(output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Score function JSONL with Jev. Stdlib only, concurrent, resumable.

Usage: python3 scripts/jev_score.py --in data/X.functions.jsonl \
         --out data/X.scores.jsonl --arm noul-auth --workers 8 [--limit N]
"""
import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.typesafe.ai/v1/systemone"

ARMS = {
    "noul-auth": {"v": {"type": "noul", "instructions": (
        "Does this function perform an authorization check before mutating state?")}},
    "choice-auth": {"v": {"type": "choice",
        "instructions": "What kind of authorization does this function perform before mutating state?",
        "criteria": {
            "explicit": "Compares actor identity/role/tenant against the target object before mutation, and blocks on failure.",
            "auth_only": "Checks login only, or checks after mutation, or the check does not gate the mutation.",
            "absent": "No authorization of any kind."}}},
    "noul-broad": {"v": {"type": "noul", "instructions": (
        "Does this function make a security decision: authorization, "
        "ownership or tenant check, state-transition guard, or sensitive write?")}},
}


def load_key():
    try:
        for line in open(os.path.join(ROOT, ".env")):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "TYPESAFE_API_KEY":
                    return v.strip()
    except FileNotFoundError:
        pass
    return os.environ.get("TYPESAFE_API_KEY")


def state_of(fn):
    code = fn["code"]
    if len(code) > 20000:
        code = code[:20000] + "\n...[truncated]"
    return f"{fn['qualified']} {fn.get('params', '')}\n{fn['file']}:{fn['start_line']}\n{code}"


def call(key, model, state, questions, tries=3):
    body = json.dumps({"model": model, "state": state, "questions": questions})
    last = ""
    for i in range(tries):
        req = urllib.request.Request(
            API, data=body.encode(),
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                b = json.loads(r.read().decode())
                return {"ok": True, "ms": (time.monotonic() - t0) * 1000,
                        "body": b}
        except urllib.error.HTTPError as e:
            last = f"HTTP{e.code}"
            if e.code not in (408, 429, 500, 502, 503, 504, 529):
                break
        except Exception as e:
            last = str(e)[:100]
        time.sleep(2 ** i)
    return {"ok": False, "ms": 0, "detail": last}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arm", choices=sorted(ARMS), required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=os.environ.get("JEV_MODEL", "jev-latest"))
    ap.add_argument("--retry-errors", action="store_true")
    a = ap.parse_args()

    if a.retry_errors and os.path.exists(a.out):
        kept = [l for l in open(a.out)
                if not (json.loads(l).get("arm") == a.arm
                        and "error" in json.loads(l))]
        with open(a.out, "w") as f:
            f.writelines(kept)

    key = load_key()
    if not key:
        print("MISSING: TYPESAFE_API_KEY")
        sys.exit(1)
    fns = [json.loads(l) for l in open(a.inp)]
    if a.limit:
        fns = fns[:a.limit]
    done = set()
    if os.path.exists(a.out):
        with open(a.out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["id"] + "|" + json.loads(line)["arm"])
                except Exception:
                    pass
    todo = [fn for fn in fns if fn["id"] + "|" + a.arm not in done]
    print(f"total={len(fns)} todo={len(todo)} arm={a.arm} model={a.model} "
          f"workers={a.workers}", flush=True)
    q = ARMS[a.arm]
    lat, tok_in, tok_out, errs = [], 0, 0, 0
    outf = open(a.out, "a")
    n = [0]

    def one(fn):
        r = call(key, a.model, state_of(fn), q)
        row = {"id": fn["id"], "arm": a.arm, "model": a.model}
        if r["ok"]:
            ans = r["body"]["answers"]["v"]
            row["answer"] = ans
            row["resolved_model"] = r["body"].get("model", a.model)
            row["ms"] = round(r["ms"])
            row["usage"] = r["body"].get("usage")
        else:
            row["error"] = r.get("detail", "")
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, fn): fn for fn in todo}
        for fut in concurrent.futures.as_completed(futs):
            row = fut.result()
            outf.write(json.dumps(row, ensure_ascii=False) + "\n")
            outf.flush()
            n[0] += 1
            if "ms" in row:
                lat.append(row["ms"])
            else:
                errs += 1
            u = row.get("usage") or {}
            tok_in += u.get("input_tokens", 0)
            tok_out += u.get("output_tokens", 0)
            if n[0] % 100 == 0:
                print(f"  {n[0]}/{len(todo)} errs={errs}", flush=True)
    outf.close()
    if lat:
        s = sorted(lat)
        print(f"done={n[0]} errs={errs} ms_min={s[0]} med={statistics.median(s):.0f} "
              f"p95={s[int(len(s) * 0.95)]} max={s[-1]} "
              f"tok_in={tok_in} tok_out={tok_out}")


if __name__ == "__main__":
    main()

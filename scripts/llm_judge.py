#!/usr/bin/env python3
"""B2: frontier judge scores the blinded review sample. Stdlib only.

Usage: python3 scripts/llm_judge.py --in eval/labels/X.review.jsonl \
         --prompt eval/baselines/llm_judge_prompt.md --out data/X.llmjudge.jsonl
"""
import argparse
import json
import os
import re
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    env = {}
    try:
        for line in open(os.path.join(ROOT, ".env")):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    env = load_env()
    key = env.get("MODEL_API_KEY") or os.environ.get("MODEL_API_KEY")
    base = env.get("FRONTIER_BASE_URL", "https://api.meta.ai/v1")
    model = env.get("FRONTIER_MODEL", "muse-spark-1.3-contributor")
    if not key:
        print("MISSING: MODEL_API_KEY")
        raise SystemExit(1)
    tpl = open(a.prompt).read()
    fns = [json.loads(l) for l in open(a.inp)]
    done = set()
    if os.path.exists(a.out):
        done = {r["id"] for r in (json.loads(l) for l in open(a.out))
                if r.get("score") is not None}
    todo = [f for f in fns if f["id"] not in done]
    print(f"total={len(fns)} todo={len(todo)} model={model}", flush=True)
    tin = tout = 0
    with open(a.out, "a") as out:
        for i, fn in enumerate(todo):
            prompt = tpl.replace("{qualified}", fn["qualified"]).replace(
                "{file}", fn["file"]).replace(
                "{line}", str(fn["id"].split(":")[2])).replace(
                "{code}", fn["code"][:6000])
            body = json.dumps({"model": model, "temperature": 0,
                               "max_tokens": 4096,
                               "messages": [{"role": "user",
                                             "content": prompt}]})
            req = urllib.request.Request(
                base + "/chat/completions", data=body.encode(),
                headers={"Authorization": "Bearer " + key,
                         "Content-Type": "application/json"})
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    b = json.loads(r.read().decode())
                txt = (b["choices"][0]["message"]["content"] or "")
                m = re.search(r"0?\.\d+|[01](?:\.0+)?", txt)
                score = float(m.group(0)) if m else None
                u = b.get("usage", {})
                tin += u.get("prompt_tokens", 0)
                tout += u.get("completion_tokens", 0)
                row = {"id": fn["id"], "arm": "llm-judge", "score": score,
                       "ms": round((time.monotonic() - t0) * 1000),
                       "raw": txt[:120]}
            except Exception as e:
                row = {"id": fn["id"], "arm": "llm-judge",
                       "error": str(e)[:150]}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if (i + 1) % 10 == 0:
                print(f"  {i + 1}/{len(todo)}", flush=True)
    print(f"tok_in={tin} tok_out={tout}")


if __name__ == "__main__":
    main()

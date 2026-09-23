#!/usr/bin/env python3
"""Stratified sample over a Jev arm for blind labeling. Stdlib only.

Usage: python3 scripts/sample.py --track mastodon --arm noul-auth \
         --n 50 --seed 7
Writes eval/labels/<track>.manifest.json, .review.jsonl (no scores, shuffled),
<track>.labels.json (template).
"""
import argparse
import json
import os
import random

ALLOC = [13, 13, 12, 12]  # top5 / 5-20 / 20-50 / rest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--arm", default="noul-auth")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--funcs", default=None)
    ap.add_argument("--scores", default=None)
    ap.add_argument("--outdir", default="eval/labels")
    a = ap.parse_args()
    funcs_p = a.funcs or f"data/{a.track}.functions.jsonl"
    scores_p = a.scores or f"data/{a.track}.scores.jsonl"

    fns = {}
    with open(funcs_p) as f:
        for line in f:
            r = json.loads(line)
            fns[r["id"]] = r
    scored = []
    with open(scores_p) as f:
        for line in f:
            r = json.loads(line)
            if r.get("arm") != a.arm or "answer" not in r:
                continue
            ans = r["answer"]
            s = ans.get("noul")
            if s is None:  # choice arm: explicit->1, else 0, tiebreak conf
                s = 1.0 if ans.get("choice") == "explicit" else 0.0
                s += (ans.get("confidence") or 0) * 1e-6
            scored.append((r["id"], s))
    scored.sort(key=lambda t: -t[1])
    n = len(scored)
    bands = [[], [], [], []]
    for i, (fid, s) in enumerate(scored):
        f = i / n
        b = 0 if f < 0.05 else 1 if f < 0.20 else 2 if f < 0.50 else 3
        bands[b].append((fid, s))

    rng = random.Random(a.seed)
    manifest = []
    for b, want in enumerate(ALLOC):
        pool = bands[b][:]
        rng.shuffle(pool)
        take = pool[:want]
        w = len(bands[b]) / len(take)
        for fid, s in take:
            manifest.append({"id": fid, "band": b, "band_pop": len(bands[b]),
                             "weight": round(w, 2)})

    os.makedirs(a.outdir, exist_ok=True)
    base = os.path.join(a.outdir, a.track)
    with open(base + ".manifest.json", "w") as f:
        json.dump({"track": a.track, "arm": a.arm, "seed": a.seed,
                   "bands": [len(b) for b in bands], "sample": manifest}, f)
    rng2 = random.Random(a.seed + 1)
    order = manifest[:]
    rng2.shuffle(order)
    with open(base + ".review.jsonl", "w") as f:
        for m in order:
            fn = fns[m["id"]]
            f.write(json.dumps({"id": fn["id"], "file": fn["file"],
                                "qualified": fn["qualified"],
                                "code": fn["code"]}, ensure_ascii=False) + "\n")
    with open(base + ".labels.json", "w") as f:
        json.dump([{"id": m["id"], "label": None, "reason": ""}
                   for m in order], f, indent=1)
    print(f"bands={[len(b) for b in bands]} sampled={len(manifest)} "
          f"seed={a.seed} -> {base}.{{manifest,review,labels}}.json*")


if __name__ == "__main__":
    main()

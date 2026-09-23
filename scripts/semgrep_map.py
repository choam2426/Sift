#!/usr/bin/env python3
"""B3: map Semgrep JSON findings to function units -> per-function scores.

Usage: python3 scripts/semgrep_map.py --in data/X.functions.jsonl \
         --findings data/X.semgrep.json --out data/X.semgrep.jsonl
"""
import argparse
import bisect
import json
import os

SEV = {"ERROR": 3, "WARNING": 2, "INFO": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default="targets/mastodon")
    a = ap.parse_args()

    by_file = {}
    order = []
    for line in open(a.inp):
        r = json.loads(line)
        order.append(r["id"])
        by_file.setdefault(r["file"], []).append(
            (r["start_line"], r["end_line"], r["id"]))
    for v in by_file.values():
        v.sort()
    starts = {k: [s for s, _, _ in v] for k, v in by_file.items()}

    score, count = {}, {}
    misses = 0
    rep = json.load(open(a.findings))
    for f in rep.get("results", []):
        rel = os.path.relpath(f["path"], a.root)
        ln = f["start"]["line"]
        lst = by_file.get(rel)
        if not lst:
            misses += 1
            continue
        i = bisect.bisect_right(starts[rel], ln) - 1
        if i < 0 or ln > lst[i][1]:
            misses += 1
            continue
        fid = lst[i][2]
        score[fid] = score.get(fid, 0) + SEV.get(f["extra"]["severity"], 1)
        count[fid] = count.get(fid, 0) + 1

    with open(a.out, "w") as out:
        for fid in order:
            out.write(json.dumps({"id": fid, "arm": "semgrep",
                                  "score": score.get(fid, 0),
                                  "findings": count.get(fid, 0)}) + "\n")
    print(f"functions={len(order)} hit={len(score)} "
          f"findings={len(rep.get('results', []))} unmapped={misses}")


if __name__ == "__main__":
    main()

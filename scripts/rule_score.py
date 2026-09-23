#!/usr/bin/env python3
"""B1: apply frozen regex rule list to function JSONL -> ranked scores.

Usage: python3 scripts/rule_score.py --in data/X.functions.jsonl \
         --rules eval/baselines/rule_list.json --out data/X.rules.jsonl
"""
import argparse
import json
import re


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rules = [(re.compile(r["pattern"]), r["weight"], r.get("reason", ""))
             for r in json.load(open(a.rules))]
    n, hits = 0, 0
    with open(a.out, "w") as out:
        for line in open(a.inp):
            fn = json.loads(line)
            text = f"{fn['qualified']}\n{fn['file']}\n{fn['code']}"
            score, matched = 0, []
            for pat, w, reason in rules:
                if pat.search(text):
                    score += w
                    matched.append(reason or pat.pattern[:40])
            n += 1
            hits += 1 if score else 0
            out.write(json.dumps({"id": fn["id"], "arm": "rule",
                                  "score": score, "matched": matched[:8]}) + "\n")
    print(f"n={n} scored={hits} rules={len(rules)}")


if __name__ == "__main__":
    main()

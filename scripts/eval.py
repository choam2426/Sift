#!/usr/bin/env python3
"""P0 eval: head-to-head ranking on the shared labeled sample. Stdlib only.

Full-set arms (jev x3, rule, semgrep): stratified recall@k/precision@k
estimated with manifest weights. Sample-only arm (llm-judge): sample AUC
+ accuracy@0.5. B0 random: analytic expectation.

Usage: python3 scripts/eval.py --track mastodon
"""
import argparse
import json
from collections import defaultdict


def load_scores(path, arm, key):
    out = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("arm") != arm:
                continue
            out[r["id"]] = key(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    a = ap.parse_args()
    t = a.track

    labels = {l["id"]: l["label"] for l in
              json.load(open(f"eval/labels/{t}.labels.json"))}
    man = json.load(open(f"eval/labels/{t}.manifest.json"))
    weight = {m["id"]: m["weight"] for m in man["sample"]}
    sample_ids = set(labels)

    def jev_noul(r):
        return r["answer"]["noul"] if "answer" in r else -1

    def jev_choice(r):
        if "answer" not in r:
            return -1
        return r["answer"].get("probabilities", {}).get("explicit", 0)

    arms = {
        "jev-noul-auth": load_scores(f"data/{t}.scores.jsonl", "noul-auth", jev_noul),
        "jev-choice": load_scores(f"data/{t}.scores.jsonl", "choice-auth", jev_choice),
        "jev-noul-broad": load_scores(f"data/{t}.scores.jsonl", "noul-broad", jev_noul),
        "rule": load_scores(f"data/{t}.rules.jsonl", "rule", lambda r: r["score"]),
        "semgrep": load_scores(f"data/{t}.semgrep.jsonl", "semgrep", lambda r: r["score"]),
    }
    judge = {r["id"]: r["score"] for r in
             (json.loads(l) for l in open(f"data/{t}.llmjudge.jsonl"))
             if r.get("score") is not None}

    N = len(next(iter(arms.values())))
    tot_pos_w = sum(labels[i] * weight[i] for i in sample_ids)
    print(f"N={N} sample={len(sample_ids)} pos=21 weighted_pos={tot_pos_w:.0f}")
    print(f"{'arm':14s} {'R@5':>6s} {'R@10':>6s} {'R@20':>6s} "
          f"{'P@5':>6s} {'P@10':>6s} {'P@20':>6s}")
    for name, scores in arms.items():
        ranked = sorted(scores, key=lambda i: (-scores[i], i))
        row = []
        for k in (0.05, 0.10, 0.20):
            top = set(ranked[:int(N * k)])
            hit = sum(labels[i] * weight[i] for i in sample_ids & top)
            row.append(hit / tot_pos_w)
        for k in (0.05, 0.10, 0.20):
            top = set(ranked[:int(N * k)])
            hit = sum(labels[i] * weight[i] for i in sample_ids & top)
            row.append(min(1.0, hit / (N * k)))  # cap: HT variance artifact
        print(f"{name:14s} " + " ".join(f"{v:6.2f}" for v in row))
    # sample-only: llm-judge AUC + acc
    ys = [(judge[i], labels[i]) for i in sample_ids if i in judge]
    ys.sort(reverse=True)
    auc_n = auc_d = 0
    for i in range(len(ys)):
        for j in range(len(ys)):
            if ys[i][1] > ys[j][1]:
                auc_d += 1
                auc_n += 1 if ys[i][0] > ys[j][0] else 0.5 if ys[i][0] == ys[j][0] else 0
    acc = sum((s >= 0.5) == bool(l) for s, l in ys) / len(ys)
    print(f"llm-judge(sample): AUC={auc_n / auc_d:.2f} acc@0.5={acc:.2f} n={len(ys)}")
    for name, scores in arms.items():
        s = [(scores[i], labels[i]) for i in sample_ids if i in scores]
        s.sort(reverse=True)
        n1 = d1 = 0
        for i in range(len(s)):
            for j in range(len(s)):
                if s[i][1] > s[j][1]:
                    d1 += 1
                    n1 += 1 if s[i][0] > s[j][0] else 0.5 if s[i][0] == s[j][0] else 0
        print(f"{name:14s} sample-AUC={n1 / d1:.2f}")
    print(f"B0 random: R@k=k, P@k={tot_pos_w / N:.3f} (prevalence est)")
    # band hit rates (stratification arm)
    by_band = defaultdict(lambda: [0, 0])
    band_of = {m["id"]: m["band"] for m in man["sample"]}
    for i in sample_ids:
        by_band[band_of[i]][1] += 1
        by_band[band_of[i]][0] += labels[i]
    print("band hit (noul-auth):", {b: f"{v[0]}/{v[1]}" for b, v in sorted(by_band.items())})


if __name__ == "__main__":
    main()

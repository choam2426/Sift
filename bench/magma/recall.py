"""Magma bench: bugs reached when reading units in an order up to a share of the code (lines), with baselines."""
import argparse, json, random
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUDGETS = (0.10, 0.15, 0.20, 0.25, 0.30)
PASS, STRETCH = {0.30: 0.70}, {0.10: 0.70, 0.30: 0.90}  # ADR 0018

def reached(order, lines, labels, budget):
    """Read whole units in order while the lines read stay within budget * all lines; count bugs with a unit read."""
    limit, used, read = budget * sum(lines.values()), 0, set()
    for u in order:
        if used + lines[u] > limit:
            break
        read.add(u); used += lines[u]
    return sum(bool(set(units) & read) for units in labels.values())

def orders(run):
    scores = {x["function_id"]: x["score"] for x in map(json.loads, open(run / "triage.jsonl"))}
    lines = {x["id"]: x["end_line"] - x["start_line"] + 1 for x in map(json.loads, open(run / "functions.jsonl"))}
    lines = {u: lines[u] for u in scores}
    q = lambda u: scores[u] if scores[u] is not None else -1
    return lines, {"stage 1": sorted(scores, key=lambda u: (-q(u), u)),
                   "longest first": sorted(scores, key=lambda u: (-lines[u], u))}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--data", type=Path, default=REPO / "data/magma", help="directory with labels-<target>.json and runs/<target>/")
    a = ap.parse_args()
    total, bugs = {}, 0
    for t in a.targets:
        labels = json.loads((a.data / f"labels-{t}.json").read_text())
        lines, named = orders(a.data / f"runs/{t}")
        bugs += len(labels)
        rows = {name: [reached(o, lines, labels, b) for b in BUDGETS] for name, o in named.items()}
        units = sorted(lines)
        runs = [random.Random(s).sample(units, len(units)) for s in range(200)]
        rows["random (mean of 200)"] = [sum(reached(o, lines, labels, b) for o in runs) / len(runs) for b in BUDGETS]
        print(f"== {t}: {len(lines)} units, {sum(lines.values())} lines, {len(labels)} bugs")
        for name, hits in rows.items():
            print(f"  {name:22}" + "".join(f"{int(b * 100):>4}%: {h:5.1f}" for b, h in zip(BUDGETS, hits)))
            total[name] = [x + y for x, y in zip(total.get(name, [0] * len(BUDGETS)), hits)]
    print(f"== total: {bugs} bugs (share of bugs reached at a share of lines)")
    for name, hits in total.items():
        share = dict(zip(BUDGETS, (h / bugs for h in hits)))
        mark = "stretch" if all(share[b] >= r for b, r in STRETCH.items()) else "pass" if all(share[b] >= r for b, r in PASS.items()) else "below"
        print(f"  {name:22}" + "".join(f"{int(b * 100):>4}%: {s:5.0%}" for b, s in share.items()) + f"  [{mark}]")

if __name__ == "__main__":
    main()

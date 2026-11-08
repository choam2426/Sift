#!/usr/bin/env python3
"""Phase 2 analysis (ADR 0010 §5). Written before any main-experiment run.

    python3 analyze.py --runs ~/sift-runs/planted/runs/main [--csv out.csv]

Reads every control/runs/*/run.json under --runs. A case's cost for an arm is
the mean all-in cost (Claude + ranking) over all of its runs, valid or not.
Ratios are per case; the summary is their geometric mean with a bootstrap
95% CI that resamples repositories (cases in a repository move together).
"""
import argparse, csv, glob, json, math, os, pathlib, random, statistics, sys

DATA = pathlib.Path('~/sift-runs/planted').expanduser()
BOOT = 10000
SEED = 20261108


def load(root):
    rows = []
    for path in sorted(glob.glob(os.path.join(os.path.expanduser(root), '**', 'control', 'runs', '*', 'run.json'), recursive=True)):
        r = json.loads(pathlib.Path(path).read_text())
        rows.append({'case': r['case'], 'arm': r['arm'], 'cost': r['total_cost_usd'], 'valid': bool(r['valid']),
                     'turns': r.get('num_turns'), 'wall': r.get('elapsed_seconds'),
                     'first_read': r.get('mutated_first_read_turn'), 'path': path})
    return rows


def case_meta(case):
    meta = json.loads((DATA / 'cases' / case / 'case.json').read_text())
    return meta['repo'], meta['units']


def per_case(rows):
    out = {}
    for r in rows:
        c = out.setdefault(r['case'], {})
        c.setdefault(r['arm'], []).append(r)
    return out


def ratio(cases, num, den):
    """{case: mean(num)/mean(den)} for cases that have both arms."""
    out = {}
    for case, arms in cases.items():
        if num in arms and den in arms:
            out[case] = statistics.mean(r['cost'] for r in arms[num]) / statistics.mean(r['cost'] for r in arms[den])
    return out


def geomean(xs):
    return math.exp(statistics.mean(math.log(x) for x in xs))


def boot_geomean(ratios, repo_of):
    repos = sorted({repo_of[c] for c in ratios})
    by_repo = {p: [ratios[c] for c in ratios if repo_of[c] == p] for p in repos}
    rng = random.Random(SEED)
    stats = []
    for _ in range(BOOT):
        xs = [x for p in (rng.choice(repos) for _ in repos) for x in by_repo[p]]
        stats.append(geomean(xs))
    stats.sort()
    return stats[int(0.025 * BOOT)], stats[int(0.975 * BOOT) - 1]


def slope(points):
    """OLS slope of y on x."""
    xs, ys = zip(*points)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else float('nan')


def boot_slope(points_by_case, repo_of):
    repos = sorted({repo_of[c] for c in points_by_case})
    rng = random.Random(SEED)
    stats = []
    for _ in range(BOOT):
        pts = [points_by_case[c] for p in (rng.choice(repos) for _ in repos) for c in points_by_case if repo_of[c] == p]
        s = slope(pts)
        if not math.isnan(s):
            stats.append(s)
    stats.sort()
    n = len(stats)
    return stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def verdict(point, hi, predicted):
    if point >= 1.0:
        return 'refuted'
    if point < predicted and hi < 1.0:
        return 'supported'
    return 'inconclusive'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', default=str(DATA / 'runs' / 'main'))
    ap.add_argument('--csv')
    args = ap.parse_args()
    rows = load(args.runs)
    if not rows:
        raise SystemExit('no runs')
    cases = per_case(rows)
    repo_of, units_of = {}, {}
    for c in cases:
        repo_of[c], units_of[c] = case_meta(c)

    print('## per case\n')
    print('| case | repo | units | arm | runs | valid | mean cost | mean turns |')
    print('| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |')
    for c in sorted(cases):
        for arm in ('vanilla', 'rank-bm25', 'rank-jev'):
            rs = cases[c].get(arm, [])
            if rs:
                turns = [r['turns'] for r in rs if r['turns'] is not None]
                print(f"| {c} | {repo_of[c]} | {units_of[c]} | {arm} | {len(rs)} | {sum(r['valid'] for r in rs)} | "
                      f"${statistics.mean(r['cost'] for r in rs):.3f} | {statistics.mean(turns) if turns else float('nan'):.1f} |")

    print('\n## hypotheses\n')
    for name, num, den, predicted in (('H1 rank-jev / vanilla', 'rank-jev', 'vanilla', 0.90),
                                      ('H2 rank-jev / rank-bm25', 'rank-jev', 'rank-bm25', 0.95),
                                      ('aux rank-bm25 / vanilla', 'rank-bm25', 'vanilla', None)):
        rs = ratio(cases, num, den)
        if len(rs) < 2:
            print(f'- {name}: not enough cases ({len(rs)})')
            continue
        g = geomean(rs.values())
        lo, hi = boot_geomean(rs, repo_of)
        v = verdict(g, hi, predicted) if predicted else 'n/a'
        print(f'- {name}: geomean {g:.3f}, 95% CI [{lo:.3f}, {hi:.3f}], cases {len(rs)}, '
              f'{sum(x < 1 for x in rs.values())}/{len(rs)} below 1 -> {v}')

    rs = ratio(cases, 'rank-jev', 'vanilla')
    if len(rs) >= 3:
        pts = {c: (math.log(units_of[c]), math.log(rs[c])) for c in rs}
        s = slope(list(pts.values()))
        lo, hi = boot_slope(pts, repo_of)
        print(f'- H3 slope of log(jev/vanilla) on log(units): {s:.3f}, 95% CI [{lo:.3f}, {hi:.3f}] (estimate only)')

    print('\n## guardrails\n')
    for arm in ('vanilla', 'rank-bm25', 'rank-jev'):
        rs = [r for r in rows if r['arm'] == arm]
        if rs:
            valid = sum(r['valid'] for r in rs)
            total = sum(r['cost'] for r in rs)
            print(f"- {arm}: valid {valid}/{len(rs)}, all-in cost per valid finding "
                  f"{'$%.3f' % (total / valid) if valid else 'n/a'}")

    if args.csv:
        with open(args.csv, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['case', 'repo', 'units', 'arm', 'cost', 'valid', 'turns', 'wall', 'first_read'])
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in w.fieldnames} | {'repo': repo_of[r['case']], 'units': units_of[r['case']]})


if __name__ == '__main__':
    sys.exit(main())

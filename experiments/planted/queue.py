#!/usr/bin/env python3
"""Pre-registered run order for the main experiment, and a runner for it.

    python3 queue.py plan --reps 3            # print the order (deterministic)
    python3 queue.py run --group main --reps 3 [--scope repo] [--cap 30]

The order is block-randomized: block r holds every (case, arm) once for
repetition r, shuffled with a seed derived from the block number, so time
effects (model or service drift over days) spread evenly across arms.
`run` executes items in order through run_one.sh, which redoes runs aborted
by session limits; finished items are skipped. Touch <group>/STOP to pause
after the current run.
"""
import argparse, json, pathlib, random, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
RUNS = pathlib.Path('~/sift-runs/planted/runs').expanduser()
ARMS = ('vanilla', 'rank-bm25', 'rank-jev')
SEED = 'phase2-main-2026-11-09'


def main_cases():
    return [c['case'] for c in json.loads((HERE / 'cases.json').read_text()) if c['role'] == 'main']


def plan(reps):
    order = []
    for rep in range(1, reps + 1):
        block = [(case, arm, rep) for case in main_cases() for arm in ARMS]
        random.Random(f'{SEED}:{rep}').shuffle(block)
        order += block
    return order


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.add_argument('--reps', type=int, required=True)
    p = sub.add_parser('run'); p.add_argument('--reps', type=int, required=True); p.add_argument('--group', default='main')
    p.add_argument('--scope', default='repo'); p.add_argument('--cap', default='30')
    args = ap.parse_args()
    order = plan(args.reps)
    if args.cmd == 'plan':
        for i, (case, arm, rep) in enumerate(order, 1):
            print(f'{i}\t{case}\t{arm}\t{rep}')
        return 0
    root = RUNS / args.group
    root.mkdir(parents=True, exist_ok=True)
    for i, (case, arm, rep) in enumerate(order, 1):
        if (root / 'STOP').exists():
            print('STOP file found; pausing', flush=True)
            return 0
        if (root / f'{case}-{arm}-r{rep}' / 'control' / 'done').exists():
            continue
        print(f'[{time.strftime("%m-%d %H:%M")}] {i}/{len(order)} {case} {arm} r{rep}', flush=True)
        with open(root / f'{case}-{arm}-r{rep}.log', 'a') as log:
            rc = subprocess.run(['sh', str(HERE / 'run_one.sh'), args.group, case, arm, str(rep), args.scope, args.cap],
                                stdout=log, stderr=subprocess.STDOUT).returncode
        tail = (root / f'{case}-{arm}-r{rep}.log').read_text().splitlines()
        done = [l for l in tail if l.startswith('done ')]
        print(f'    rc={rc} {done[-1] if done else tail[-1] if tail else ""}', flush=True)
    print('queue finished', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

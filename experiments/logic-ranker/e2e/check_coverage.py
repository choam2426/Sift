#!/usr/bin/env python3
"""Check that a route bundle contains the target decision-path unit.

Usage:
  python3 check_coverage.py --case gotify --routes /path/routes.jsonl
  python3 check_coverage.py --case gotify --routes-dir /path/to/routes
"""
import argparse
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def load_case(case_id):
    data = json.loads((HERE / 'heldout-candidates.json').read_text())
    for case in data['cases']:
        if case['id'] == case_id:
            return case
    raise SystemExit(f'unknown case: {case_id}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', required=True)
    ap.add_argument('--routes')
    ap.add_argument('--routes-dir')
    args = ap.parse_args()
    case = load_case(args.case)
    if args.routes:
        path = pathlib.Path(args.routes)
    elif args.routes_dir:
        path = pathlib.Path(args.routes_dir) / f"{args.case}-p0" / 'routes.jsonl'
    else:
        raise SystemExit('pass --routes or --routes-dir')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    target_ids = set(case.get('target_route_ids', []))
    target_handlers = case.get('target_handlers', [])
    fix_functions = set(case.get('fix_functions', []))
    matches = []
    for r in rows:
        if r['ID'] not in target_ids:
            continue
        if target_handlers and not any(h in r['Handler'] for h in target_handlers):
            continue
        matches.append(r)
    problems = []
    if not matches:
        problems.append('target route/handler not found')
    if any(r.get('Truncated') for r in matches):
        problems.append('target route is truncated')
    if fix_functions and not any(fix_functions & set(r.get('Members') or []) for r in matches):
        problems.append('target Members do not include a fix-touched function')
    result = {
        'case': args.case,
        'routes': str(path),
        'target_ids': sorted(target_ids),
        'target_handlers': target_handlers,
        'fix_functions': sorted(fix_functions),
        'matches': [
            {'ID': r['ID'], 'Handler': r['Handler'], 'Truncated': r.get('Truncated'),
             'Chars': r.get('Chars'), 'members': len(r.get('Members') or [])}
            for r in matches
        ],
        'problems': problems,
        'passed': not problems,
    }
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()

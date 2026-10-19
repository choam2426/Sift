#!/usr/bin/env python3
"""Print stage-1 ranker results for routes or units."""
import argparse, json, math, pathlib

def load(path):
    return [json.loads(line) for line in path.open()]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', choices=('routes', 'units'), default='routes')
    ap.add_argument('--data-root', default=str(pathlib.Path.home() / 'sift-runs/logic-ranker'))
    args = ap.parse_args()
    root = pathlib.Path(args.data_root)
    cases = json.loads((pathlib.Path(__file__).with_name('cases.json')).read_text())
    print(f'{"case":10} {"target":55} {"rank":>10} {"pct":>7} {"len_rank":>10} {"len_pct":>8}')
    for case in cases:
        data = root / case['id'] / f'{args.kind}.jsonl'
        scores = root / case['id'] / f'{args.kind}-scores.jsonl'
        if not data.exists() or not scores.exists():
            continue
        rows = load(data)
        by_id = {row.get('ID') or row.get('id'): row for row in rows}
        score = {row['unit_id']: row for row in load(scores)}
        target = case['target_route'] if args.kind == 'routes' else case['target_entry']
        ranked = sorted(rows, key=lambda row: (-score[row.get('ID') or row.get('id')].get('noul', -1), row.get('ID') or row.get('id')))
        rank = {row.get('ID') or row.get('id'): i + 1 for i, row in enumerate(ranked)}
        length = sorted(rows, key=lambda row: (-(row.get('Chars') or row.get('chars', 0)), row.get('ID') or row.get('id')))
        lrank = {row.get('ID') or row.get('id'): i + 1 for i, row in enumerate(length)}
        n = len(rows)
        r = rank.get(target)
        lr = lrank.get(target)
        print(f'{case["id"]:10} {target[:55]:55} {str(r) + "/" + str(n):>10} {r/n:7.3f} {str(lr) + "/" + str(n):>10} {lr/n:8.3f}')

if __name__ == '__main__':
    main()

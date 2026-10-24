#!/usr/bin/env python3
"""Collapse function units into file-level decision units.

Usage: file_units.py --functions functions.jsonl --out files.jsonl [--cap 80000]
"""
import argparse
import json
import pathlib
from collections import OrderedDict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--functions', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cap', type=int, default=80000)
    args = ap.parse_args()
    groups = OrderedDict()
    for line in pathlib.Path(args.functions).read_text().splitlines():
        row = json.loads(line)
        key = row.get('file') or row.get('package') or '<root>'
        groups.setdefault(key, []).append(row)
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w') as f:
        for file, rows in sorted(groups.items()):
            rows.sort(key=lambda r: (r.get('line', 0), r.get('id', '')))
            parts, members = [], []
            for r in rows:
                block = f"Function {r['id']}:\n{r['text']}\n\n"
                if len(''.join(parts)) + len(block) > args.cap:
                    break
                parts.append(block)
                members.append(r['id'])
            if not parts:
                continue
            text = ''.join(parts)
            unit = {
                'id': f'file:{file}',
                'target': file,
                'package': rows[0].get('package', ''),
                'members': members,
                'chars': len(text),
                'text': text,
                'truncated': len(members) < len(rows),
            }
            f.write(json.dumps(unit, ensure_ascii=False) + '\n')
    print(f'files={len(groups)}')


if __name__ == '__main__':
    main()

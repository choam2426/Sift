#!/usr/bin/env python3
"""Golden SSA enrichment test. Run from this directory: python3 golden_test.py."""
import json
import pathlib
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / 'fixture'
        app = root / 'app'
        app.mkdir(parents=True)
        (root / 'go.mod').write_text('module example.com/fixture\n\ngo 1.24\n')
        (app / 'app.go').write_text('''package app

func Handler() { Check() }
func Check() {}
''')
        routes = pathlib.Path(tmp) / 'routes.jsonl'
        out = pathlib.Path(tmp) / 'out' / 'routes.jsonl'
        routes.write_text(json.dumps({
            'ID': 'route:GET /x', 'Method': 'GET', 'Path': '/x', 'Handler': 'app.Handler',
            'Members': ['app.Handler'], 'Chars': 10, 'Text': 'Route: GET /x', 'Truncated': False,
        }) + '\n')
        proc = subprocess.run(
            ['go', 'run', '.', '-root', str(root), '-pkgs', './app',
             '-routes', str(routes), '-out', str(out),
             '-max-depth', '2', '-max-sources', '4', '-max-index', '20'],
            cwd=HERE, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stdout + proc.stderr)
        row = json.loads(out.read_text().splitlines()[0])
        assert 'app.Check' in row['Members'], row['Members']
        assert 'Function app.Check' in row['Text'], row['Text']
        assert not row['Truncated'], row
        print('golden SSA enrichment test: ok')


if __name__ == '__main__':
    main()

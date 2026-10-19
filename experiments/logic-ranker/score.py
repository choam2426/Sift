#!/usr/bin/env python3
"""Score logic-ranker units with Jev 1.14.0.

    python3 score.py --kind routes --data-root ~/sift-runs/logic-ranker
    python3 score.py --kind units  --data-root ~/sift-runs/logic-ranker

The data root contains <project>/routes.jsonl or <project>/units.jsonl,
produced by extract_routes or extract_units. API key is read from the
repository's .env (TYPESAFE_API_KEY) and is never printed.
"""
import argparse, concurrent.futures, json, os, pathlib, threading, time, urllib.error, urllib.request

MODEL = 'jev-1.14.0'
CRIT = {
    'true': 'The shown path contains a check that enforces the stated invariant before the protected operation.',
    'false': 'The shown path lacks that check, applies it after the protected operation, or the check does not cover the value or object actually used.',
}

def api_key():
    root = pathlib.Path(__file__).resolve().parents[2]
    for line in (root / '.env').read_text(errors='ignore').splitlines():
        name, sep, value = line.partition('=')
        if sep and name.strip() == 'TYPESAFE_API_KEY':
            return value.strip().strip('"').strip("'")
    raise SystemExit('TYPESAFE_API_KEY is not set in .env')

KEY = api_key()

def ask(state, question):
    body = json.dumps({'model': MODEL, 'state': state, 'questions': {'q': {
        'type': 'noul', 'instructions': question, 'criteria': CRIT}}}).encode()
    req = urllib.request.Request('https://api.typesafe.ai/v1/systemone', data=body,
                                 headers={'Authorization': 'Bearer ' + KEY,
                                          'Content-Type': 'application/json'})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.load(response)
            return {'status': 'scored', 'noul': data['answers']['q']['noul'],
                    'model': data.get('model'), 'usage': data.get('usage')}
        except urllib.error.HTTPError as error:
            last = error
            if error.code in (408, 429, 500, 502, 503, 504, 529):
                time.sleep(min(1.5 * (attempt + 1), 8))
                continue
            return {'status': 'error', 'error': f'HTTP {error.code}',
                    'detail': error.read().decode(errors='replace')[:300]}
        except Exception as error:
            last = error
            time.sleep(min(1.5 * (attempt + 1), 8))
    return {'status': 'error', 'error': type(last).__name__ if last else 'transport'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', choices=('routes', 'units'), default='routes')
    ap.add_argument('--data-root', default=str(pathlib.Path.home() / 'sift-runs/logic-ranker'))
    ap.add_argument('--project', action='append')
    args = ap.parse_args()
    cases = json.loads((pathlib.Path(__file__).with_name('cases.json')).read_text())
    root = pathlib.Path(args.data_root)
    for case in cases:
        if args.project and case['id'] not in args.project:
            continue
        source = root / case['id'] / f'{args.kind}.jsonl'
        if not source.exists():
            print(f'skip {case["id"]}: {source} missing')
            continue
        rows = [json.loads(line) for line in source.open()]
        output = root / case['id'] / f'{args.kind}-scores.jsonl'
        output.write_text('')
        done = 0
        lock = threading.Lock()

        def work(row):
            nonlocal done
            state = 'Unit profile: route decision-path\nCode:\n' + row['Text'] if args.kind == 'routes' else 'Unit profile: decision-path\nCode:\n' + row['Text']
            result = ask(state, case['question'])
            record = {'unit_id': row.get('ID') or row.get('id'), 'chars': row.get('Chars') or row.get('chars', 0),
                      'members': row.get('Members') or row.get('members', []), **result}
            with lock:
                with output.open('a') as sink:
                    sink.write(json.dumps(record) + '\n')
                done += 1
                if done % 100 == 0:
                    print(f'{case["id"]}: {done}/{len(rows)}', flush=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work, rows))
        print(f'{case["id"]}: wrote {output} ({done} rows)', flush=True)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Rank file units for one question with BM25 or Jev.

    python3 rank.py --units units.jsonl --ranker bm25|jev --out ranking.tsv [--calls calls.jsonl]

Output rows: rank<TAB>path. Jev calls are logged with usage so a run can be
replayed (--replay calls.jsonl) and costed. Unscored units go last in ID order.
"""
import argparse, concurrent.futures, json, math, pathlib, re, sys, threading, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
QUESTION = ("Does this code enforce the caller's authorization for the resource and context "
            "it actually operates on before the protected operation?")
JEV_MODEL = 'jev-1.14.0'
JEV_PRICE_PER_MTOK = 0.042
# same criteria and state framing as the Phase 1 proxy and CLI (experiments/logic-ranker/e2e)
CRIT = {
    'true': 'The shown path contains a check that enforces the stated invariant before the protected operation.',
    'false': 'The shown path lacks that check, applies it after the protected operation, or the check does not cover the value or object actually used.',
}


def tokens(text):
    out = []
    for w in re.findall(r'[A-Za-z][A-Za-z0-9]*', text):
        for part in re.findall(r'[A-Z]+(?=[A-Z][a-z]|\b|[0-9])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+', w):
            if len(part) > 1:
                out.append(part.lower())
    return out


def bm25(units, question, k1=1.2, b=0.75):
    docs = [tokens(u['target'] + '\n' + u['text']) for u in units]
    n = len(docs)
    avg = sum(map(len, docs)) / max(n, 1)
    df = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    q = tokens(question)
    scores = []
    for d in docs:
        tf = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def read_key():
    for line in (ROOT / '.env').read_text(errors='ignore').splitlines():
        name, sep, value = line.partition('=')
        if sep and name.strip() == 'TYPESAFE_API_KEY':
            return value.strip().strip('"').strip("'")
    raise SystemExit('TYPESAFE_API_KEY missing')


def jev_one(key, text, question):
    body = json.dumps({'model': JEV_MODEL, 'state': 'Unit profile: route decision-path\nCode:\n' + text,
                       'questions': {'q': {'type': 'noul', 'instructions': question, 'criteria': CRIT}}}).encode()
    req = urllib.request.Request('https://api.typesafe.ai/v1/systemone', data=body,
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            return {'status': 'scored', 'noul': float(data['answers']['q']['noul']), 'model': data.get('model'),
                    'usage': data.get('usage') or {}}
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code in (408, 429, 500, 502, 503, 504, 529):
                time.sleep(min(2 * (attempt + 1), 15))
                continue
            return {'status': 'error', 'error': last, 'detail': e.read().decode(errors='replace')[:300]}
        except Exception as e:
            last = type(e).__name__
            time.sleep(min(2 * (attempt + 1), 15))
    return {'status': 'error', 'error': last or 'transport'}


def jev(units, question, calls_path, replay=None, workers=8):
    cached = {}
    if replay:
        for line in pathlib.Path(replay).read_text().splitlines():
            r = json.loads(line)
            cached[r['id']] = r['result']
    key = None if replay else read_key()
    lock = threading.Lock()
    results = {}
    started = time.monotonic()
    with open(calls_path, 'w') as log:
        def score(u):
            res = cached.get(u['id']) if replay else jev_one(key, u['text'], question)
            with lock:
                results[u['id']] = res
                log.write(json.dumps({'id': u['id'], 'chars': len(u['text']), 'result': res}) + '\n')
        with concurrent.futures.ThreadPoolExecutor(workers) as ex:
            list(ex.map(score, units))
    toks = sum(int((r.get('usage') or {}).get('input_tokens') or 0) for r in results.values() if r)
    errors = sum(1 for r in results.values() if not r or r.get('status') != 'scored')
    scores = [results[u['id']]['noul'] if results.get(u['id'], {}).get('status') == 'scored' else None for u in units]
    return scores, {'requests': len(units), 'errors': errors, 'input_tokens': toks,
                    'cost_usd': round(toks * JEV_PRICE_PER_MTOK / 1e6, 6),
                    'seconds': round(time.monotonic() - started, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--units', required=True)
    ap.add_argument('--ranker', choices=('bm25', 'jev'), required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--calls')
    ap.add_argument('--replay')
    ap.add_argument('--question', default=QUESTION)
    args = ap.parse_args()
    units = [json.loads(l) for l in open(args.units) if l.strip()]
    if args.ranker == 'bm25':
        scores, stats = bm25(units, args.question), {'requests': 0, 'cost_usd': 0.0}
    else:
        scores, stats = jev(units, args.question, args.calls or args.out + '.calls.jsonl', args.replay)
    order = sorted(range(len(units)), key=lambda i: (scores[i] is None, -(scores[i] or 0), units[i]['id']))
    with open(args.out, 'w') as f:
        for rank, i in enumerate(order, 1):
            f.write(f"{rank}\t{units[i]['target']}\n")
    with open(args.out + '.scores.jsonl', 'w') as f:
        for rank, i in enumerate(order, 1):
            f.write(json.dumps({'rank': rank, 'path': units[i]['target'], 'score': scores[i]}) + '\n')
    stats['units'] = len(units)
    print(json.dumps(stats))


if __name__ == '__main__':
    sys.exit(main())

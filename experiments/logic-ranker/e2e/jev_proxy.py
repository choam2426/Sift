#!/usr/bin/env python3
"""Unix-socket proxy that holds the TypeSafe key and logs Jev ranker calls."""
import argparse, json, os, pathlib, socketserver, threading, time, urllib.error, urllib.request

MODEL = 'jev-1.14.0'
CRIT = {
    'true': 'The shown path contains a check that enforces the stated invariant before the protected operation.',
    'false': 'The shown path lacks that check, applies it after the protected operation, or the check does not cover the value or object actually used.',
}

def read_key():
    root = pathlib.Path(__file__).resolve().parents[3]
    for line in (root / '.env').read_text(errors='ignore').splitlines():
        name, sep, value = line.partition('=')
        if sep and name.strip() == 'TYPESAFE_API_KEY':
            return value.strip().strip('"').strip("'")
    raise SystemExit('TYPESAFE_API_KEY missing')

class State:
    def __init__(self, log_path, max_requests, max_input_tokens):
        self.log_path = log_path
        self.max_requests = max_requests
        self.max_input_tokens = max_input_tokens
        self.requests = 0
        self.input_tokens = 0
        self.lock = threading.Lock()
        self.key = read_key()

def ask(state, payload):
    question = str(payload.get('question', ''))
    text = str(payload.get('state', ''))
    if not question:
        return {'status': 'error', 'error': 'question is required'}
    with state.lock:
        if state.requests >= state.max_requests:
            return {'status': 'error', 'error': 'Jev request budget exhausted'}
        state.requests += 1
    body = json.dumps({'model': MODEL, 'state': text, 'questions': {'q': {
        'type': 'noul', 'instructions': question, 'criteria': CRIT}}}).encode()
    req = urllib.request.Request('https://api.typesafe.ai/v1/systemone', data=body,
                                 headers={'Authorization': 'Bearer ' + state.key,
                                          'Content-Type': 'application/json'})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.load(response)
            usage = data.get('usage') or {}
            result = {'status': 'scored', 'noul': data['answers']['q']['noul'],
                      'model': data.get('model'), 'usage': usage}
            with state.lock:
                state.input_tokens += int(usage.get('input_tokens') or 0)
                if state.input_tokens > state.max_input_tokens:
                    result = {'status': 'error', 'error': 'Jev input token budget exhausted'}
            return result
        except urllib.error.HTTPError as error:
            last = error
            if error.code in (408, 429, 500, 502, 503, 504, 529):
                time.sleep(min(1.5 * (attempt + 1), 8)); continue
            return {'status': 'error', 'error': f'HTTP {error.code}',
                    'detail': error.read().decode(errors='replace')[:300]}
        except Exception as error:
            last = error; time.sleep(min(1.5 * (attempt + 1), 8))
    return {'status': 'error', 'error': type(last).__name__ if last else 'transport'}

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        try:
            payload = json.loads(line)
        except Exception:
            self.wfile.write((json.dumps({'status': 'error', 'error': 'invalid json'}) + '\n').encode()); return
        state = self.server.state
        if payload.get('op') == 'stats':
            result = {'status': 'ok', 'model': MODEL, 'requests': state.requests,
                      'input_tokens': state.input_tokens}
        else:
            result = ask(state, payload)
        with state.lock:
            with state.log_path.open('a') as sink:
                sink.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                                       'question': payload.get('question', ''),
                                       'state_chars': len(str(payload.get('state', ''))),
                                       'result': result}) + '\n')
        self.wfile.write((json.dumps(result) + '\n').encode())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--socket', required=True)
    ap.add_argument('--log', required=True)
    ap.add_argument('--max-requests', type=int, default=500)
    ap.add_argument('--max-input-tokens', type=int, default=2_000_000)
    args = ap.parse_args()
    pathlib.Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(args.socket):
        os.unlink(args.socket)
    server = socketserver.UnixStreamServer(args.socket, Handler)
    server.state = State(pathlib.Path(args.log), args.max_requests, args.max_input_tokens)
    os.chmod(args.socket, 0o600)
    server.serve_forever()

if __name__ == '__main__':
    main()

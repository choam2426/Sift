#!/usr/bin/env python3
"""Workspace-side Jev ranker CLI. It never sees the API key."""
import argparse, json, os, socket, sys

SOCKET = os.environ.get('JEV_SOCKET', '')

def ask(payload):
    if not SOCKET:
        raise SystemExit('JEV_SOCKET is not set')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(SOCKET)
        sock.sendall((json.dumps(payload) + '\n').encode())
        data = b''
        while not data.endswith(b'\n'):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode())

def main():
    ap = argparse.ArgumentParser(description='Jev ranker: score candidate units. Scores are priorities, not proof.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('ask', help='ask one Noul question about a state file')
    p.add_argument('--state', required=True)
    p.add_argument('--question', required=True)
    p = sub.add_parser('rank', help='score route/unit JSONL and print top units')
    p.add_argument('--units', required=True)
    p.add_argument('--question', required=True)
    p.add_argument('--top', type=int, default=20)
    p.add_argument('--field', default='Text')
    sub.add_parser('stats', help='show Jev request/token usage')
    args = ap.parse_args()
    if args.cmd == 'ask':
        result = ask({'state': open(args.state).read(), 'question': args.question})
        print(json.dumps(result, indent=2))
        return 0 if result.get('status') == 'scored' else 2
    if args.cmd == 'stats':
        print(json.dumps(ask({'op': 'stats'}), indent=2)); return 0
    rows = [json.loads(line) for line in open(args.units) if line.strip()]
    scored = []
    for row in rows:
        text = row.get(args.field) or row.get('Text') or row.get('text') or ''
        result = ask({'state': 'Unit profile: route decision-path\nCode:\n' + text,
                      'question': args.question})
        if result.get('status') == 'scored':
            scored.append((float(result['noul']), row.get('ID') or row.get('id'), row.get('Path') or row.get('Handler') or ''))
    scored.sort(key=lambda item: (-item[0], item[1]))
    limit = len(scored) if args.top <= 0 else min(args.top, len(scored))
    for score, unit_id, extra in scored[:limit]:
        print(f'{score:.4f}\t{unit_id}\t{extra}')
    return 0

if __name__ == '__main__':
    sys.exit(main())

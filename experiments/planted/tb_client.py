#!/usr/bin/env python3
"""Agent-side ./tb: forwards test/build/exec to the harness broker."""
import base64, json, os, select, socket, sys


def main():
    path = os.environ.get('TB_SOCKET', '')
    data = None
    if not sys.stdin.isatty():
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        if ready:
            data = sys.stdin.buffer.read()
    req = {'argv': sys.argv[1:], 'stdin': base64.b64encode(data).decode() if data else None}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(path)
        s.sendall((json.dumps(req) + '\n').encode())
        f = s.makefile('rb')
        for line in f:
            msg = json.loads(line)
            if 'o' in msg:
                sys.stdout.write(msg['o'])
                sys.stdout.flush()
            if 'exit' in msg:
                return msg['exit']
    return 1


if __name__ == '__main__':
    sys.exit(main())

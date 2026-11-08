#!/usr/bin/env python3
"""Host-side broker for the agent's ./tb tool.

The agent sandbox can reach only this Unix socket, never the Docker socket.
Requests are {"argv": [...], "stdin": "<base64>"|null}; the broker runs
`go test`, a compile check, or an arbitrary command inside the run's
container (no network) and streams {"o": text} lines, then {"exit": n}.
Every request is logged.
"""
import argparse, base64, json, os, pathlib, socketserver, subprocess, threading, time

TIMEOUT = 1800


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        cfg = self.server.cfg
        started = time.monotonic()
        try:
            req = json.loads(self.rfile.readline())
            argv = [str(a) for a in req.get('argv') or []]
            stdin = base64.b64decode(req['stdin']) if req.get('stdin') else None
        except Exception:
            self.send({'o': 'tb: bad request\n'}); self.send({'exit': 2}); return
        sub, rest = (argv[0], argv[1:]) if argv else ('', [])
        if sub == 'test':
            cmd = ['go', 'test', *rest]
        elif sub == 'build':
            cmd = ['go', 'test', '-run', '^$', *rest]
        elif sub == 'exec' and rest:
            cmd = rest
        else:
            self.send({'o': 'usage: ./tb test <go test args> | ./tb build <packages> | ./tb exec <command...>\n'})
            self.send({'exit': 2})
            return
        docker = ['docker', 'exec', *(['-i'] if stdin is not None else []), '-w', cfg['workdir'],
                  cfg['container'], 'timeout', '-s', 'KILL', str(TIMEOUT), *cmd]
        proc = subprocess.Popen(docker, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if stdin is not None:
            threading.Thread(target=lambda: (proc.stdin.write(stdin), proc.stdin.close()), daemon=True).start()
        size = 0
        try:
            for chunk in iter(lambda: proc.stdout.read1(65536), b''):
                size += len(chunk)
                self.send({'o': chunk.decode(errors='replace')})
        except (BrokenPipeError, ConnectionResetError):
            proc.kill()
        code = proc.wait()
        try:
            self.send({'exit': code})
        except (BrokenPipeError, ConnectionResetError):
            pass
        with self.server.lock, open(cfg['log'], 'a') as f:
            f.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'argv': argv,
                                'stdin_bytes': len(stdin) if stdin is not None else 0, 'exit': code,
                                'output_bytes': size, 'seconds': round(time.monotonic() - started, 1)}) + '\n')

    def send(self, obj):
        self.wfile.write((json.dumps(obj) + '\n').encode())
        self.wfile.flush()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--socket', required=True)
    ap.add_argument('--container', required=True)
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--log', required=True)
    args = ap.parse_args()
    if os.path.exists(args.socket):
        os.unlink(args.socket)
    server = Server(args.socket, Handler)
    server.cfg = {'container': args.container, 'workdir': args.workdir, 'log': args.log}
    server.lock = threading.Lock()
    os.chmod(args.socket, 0o600)
    server.serve_forever()


if __name__ == '__main__':
    main()

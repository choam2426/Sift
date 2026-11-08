#!/usr/bin/env python3
"""Find planted-defect candidates that existing package tests detect.

    python3 pool.py list --repo gitea
    python3 pool.py kill --repo gitea --target 12 --workers 2

Candidates are tried in a seeded random order. A candidate is `killed` when a
test in its own package passes on the original and fails on the mutant. Taking
killed candidates in this order is a random sample of the killed set.
"""
import argparse, hashlib, json, pathlib, random, re, shutil, subprocess, sys, threading, time

HERE = pathlib.Path(__file__).resolve().parent
REPOS = json.loads((HERE / 'repos.json').read_text())
DATA = pathlib.Path('~/sift-runs/planted').expanduser()
PLANT = HERE / 'plant' / 'plant-linux'
MODCACHE = 'sift-planted-modcache'


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def gocache(repo):
    vol = f'sift-planted-gocache-{repo}'
    if sh(['docker', 'volume', 'inspect', vol]).returncode:
        sh(['docker', 'volume', 'create', vol])
        sh(['docker', 'run', '--rm', '-v', f'{vol}:/c', 'alpine:3.20', 'chown', '1000:1000', '/c'])
    return vol


def container(repo, src, name):
    cfg = REPOS[repo]
    env = ['-e', 'GOPROXY=off', '-e', 'GOTOOLCHAIN=local', '-e', 'HOME=/tmp', '-e', 'GOCACHE=/gocache',
           '-e', 'GOFLAGS=' + cfg.get('goflags', '-mod=mod')]
    for k, v in cfg.get('env', {}).items():
        env += ['-e', f'{k}={v}']
    sh(['docker', 'rm', '-f', name])
    p = sh(['docker', 'run', '-d', '--name', name, '--network', 'none', '-m', cfg.get('mem', '3g'),
            '--user', '1000:1000', '-v', f'{src}:/src', '-w', '/src',
            '-v', f'{MODCACHE}:/go/pkg/mod:ro', '-v', f'{gocache(repo)}:/gocache',
            '-v', f'{PLANT}:/plant:ro', '-v', f'{DATA / "src" / repo}:/pristine:ro',
            *env, cfg['image'], 'sleep', 'infinity'])
    if p.returncode:
        raise SystemExit(p.stderr)
    return name


def container_hash(name, rel):
    p = sh(['docker', 'exec', name, 'sha256sum', '/src/' + rel])
    return p.stdout.split()[0] if p.returncode == 0 else None


def go_test(name, pkg, timeout):
    p = sh(['docker', 'exec', name, 'go', 'test', '-count=1', '-json', f'-timeout={timeout}s', './' + pkg],
           timeout=timeout + 300)
    return parse_test_json(p.stdout, p.stderr)


def parse_test_json(out, err):
    tests, build_failed, output = {}, False, []
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            output.append(line)
            continue
        if ev.get('Action') == 'build-fail' or ev.get('Action') == 'build-output':
            build_failed = build_failed or ev.get('Action') == 'build-fail'
            output.append(ev.get('Output', ''))
        test = ev.get('Test')
        if test and ev.get('Action') in ('pass', 'fail', 'skip'):
            tests[test] = ev['Action']
        if not test and ev.get('Action') == 'output':
            output.append(ev.get('Output', ''))
    text = ''.join(output) + err
    if re.search(r'\[build failed\]|\[setup failed\]', text) or (build_failed and not tests):
        return {'status': 'nocompile', 'tests': tests, 'tail': text[-2000:]}
    return {'status': 'ran', 'tests': tests, 'tail': text[-2000:]}


def cmd_prepare(args):
    cfg = REPOS[args.repo]
    src = DATA / 'src' / args.repo
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        for cmd in (['git', 'init', '-q', str(src)], ['git', '-C', str(src), 'remote', 'add', 'origin', cfg['url']],
                    ['git', '-C', str(src), 'fetch', '-q', '--depth=1', 'origin', cfg['commit']],
                    ['git', '-C', str(src), 'checkout', '-q', 'FETCH_HEAD']):
            if sh(cmd).returncode:
                raise SystemExit(f'failed: {cmd}')
    head = sh(['git', '-C', str(src), 'rev-parse', 'HEAD']).stdout.strip()
    if head != cfg['commit']:
        raise SystemExit(f'{args.repo}: HEAD {head} != pinned {cfg["commit"]}')
    for rel in cfg.get('placeholders', []):
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists():
            f.write_text('<html></html>\n')
    print(f'{args.repo}: {head[:12]} ready')


def cmd_list(args):
    src = DATA / 'src' / args.repo
    out = DATA / 'pool' / args.repo
    out.mkdir(parents=True, exist_ok=True)
    p = sh(['docker', 'run', '--rm', '-v', f'{PLANT}:/plant:ro', '-v', f'{src}:/src:ro', 'alpine:3.20',
            '/plant', 'list', '-root', '/src'])
    if p.returncode:
        raise SystemExit(p.stderr)
    (out / 'candidates.jsonl').write_text(p.stdout)
    print(f'{args.repo}: {len(p.stdout.splitlines())} candidates')


def cmd_kill(args):
    cfg = REPOS[args.repo]
    src = DATA / 'src' / args.repo
    out = DATA / 'pool' / args.repo
    cands = [json.loads(l) for l in (out / 'candidates.jsonl').read_text().splitlines()]
    order = sorted(cands, key=lambda c: c['id'])
    random.Random(f"{cfg['seed']}:{args.repo}").shuffle(order)
    results_path = out / 'kills.jsonl'
    done = {}
    if results_path.exists():
        for l in results_path.read_text().splitlines():
            r = json.loads(l)
            if args.retry_broken and r['status'] in ('baseline-broken', 'apply-failed'):
                continue
            done[r['id']] = r
        if args.retry_broken:
            results_path.write_text(''.join(json.dumps(r) + '\n' for r in done.values()))
            for b in (out / 'baseline').glob('*.json'):
                if json.loads(b.read_text())['status'] != 'ran':
                    b.unlink()
    has_tests = lambda pkg: any((src / pkg).glob('*_test.go'))
    lock = threading.Lock()
    baselines = {}
    base_lock = {}
    queue = [(i, c) for i, c in enumerate(order) if c['id'] not in done]
    ranks = {r['rank']: r['status'] for r in done.values()}

    def prefix_killed():
        # killed candidates in the contiguous evaluated prefix of the seeded order
        n, i = 0, 0
        while i in ranks:
            n += ranks[i] == 'killed'
            i += 1
        return n

    def worker(w):
        work = DATA / 'work' / f'{args.repo}-w{w}'
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(src, work, symlinks=True)
        name = container(args.repo, work, f'sift-pool-{args.repo}-w{w}')
        try:
            while True:
                with lock:
                    if prefix_killed() >= args.target or not queue:
                        return
                    rank, c = queue.pop(0)
                rec = {'id': c['id'], 'rank': rank, 'op': c['op'], 'file': c['file'], 'package': c['package'],
                       'func': c['func'], 'line': c['line']}
                if not has_tests(c['package']):
                    rec['status'] = 'notests'
                else:
                    with lock:
                        ev = base_lock.setdefault(c['package'], threading.Event())
                        first = c['package'] not in baselines
                        if first:
                            baselines[c['package']] = None
                    if first:
                        b = go_test(name, c['package'], args.timeout)
                        baselines[c['package']] = b
                        (out / 'baseline').mkdir(exist_ok=True)
                        (out / 'baseline' / (c['package'].replace('/', '__') + '.json')).write_text(json.dumps(b))
                        ev.set()
                    ev.wait()
                    base = baselines[c['package']]
                    want = hashlib.sha256((src / c['file']).read_bytes()).hexdigest()
                    started = time.monotonic()
                    try:
                        # all edits happen inside the container: host-side writes can be
                        # seen stale through the Docker Desktop file share
                        if container_hash(name, c['file']) != want:
                            raise RuntimeError(f'work copy of {c["file"]} is not pristine before apply')
                        p = sh(['docker', 'exec', name, '/plant', 'apply', '-root', '/src', '-id', c['id']])
                        if p.returncode:
                            rec.update(status='apply-failed', error=p.stderr[-500:])
                        elif base['status'] != 'ran':
                            rec.update(status='baseline-broken')
                        else:
                            m = go_test(name, c['package'], args.timeout)
                            if m['status'] == 'nocompile':
                                rec.update(status='nocompile', tail=m['tail'][-600:])
                            else:
                                killers = sorted(t for t, a in m['tests'].items()
                                                 if a == 'fail' and base['tests'].get(t) == 'pass')
                                rec.update(status='killed' if killers else 'survived', killers=killers)
                    except subprocess.TimeoutExpired:
                        rec['status'] = 'timeout'
                    finally:
                        sh(['docker', 'exec', name, 'cp', '/pristine/' + c['file'], '/src/' + c['file']])
                        if container_hash(name, c['file']) != want:
                            raise RuntimeError(f'failed to restore {c["file"]}')
                    rec['seconds'] = round(time.monotonic() - started, 1)
                with lock:
                    ranks[rank] = rec['status']
                    with results_path.open('a') as f:
                        f.write(json.dumps(rec) + '\n')
                    print(f"[{args.repo} w{w}] #{rank} {rec['status']:9s} {c['op']} {c['file']}:{c['line']} "
                          f"{','.join(rec.get('killers', [])[:3])} prefix_killed={prefix_killed()}/{args.target}", flush=True)
        finally:
            sh(['docker', 'rm', '-f', name])

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f'{args.repo}: prefix killed {prefix_killed()}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--repo', required=True)
    p = sub.add_parser('list'); p.add_argument('--repo', required=True)
    p = sub.add_parser('kill'); p.add_argument('--repo', required=True); p.add_argument('--target', type=int, default=12)
    p.add_argument('--workers', type=int, default=2); p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--retry-broken', action='store_true')
    args = ap.parse_args()
    return {'prepare': cmd_prepare, 'list': cmd_list, 'kill': cmd_kill}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())

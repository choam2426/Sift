#!/usr/bin/env python3
"""Build a planted-defect case from a killed pool candidate.

    python3 case.py build --repo gitea --id <candidate-id> --case gitea-1

Produces ~/sift-runs/planted/cases/<case>/:
  fix/      original source with the detecting tests removed (no .git)
  vuln/     fix/ plus the mutation; the agent sees a copy of this tree
  units.jsonl  file-level units of vuln/ (relative paths)
  case.json
The two trees differ only in the mutated file.
"""
import argparse, json, pathlib, re, shutil, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPOS = json.loads((HERE / 'repos.json').read_text())
DATA = pathlib.Path('~/sift-runs/planted').expanduser()
PLANT = HERE / 'plant' / 'plant-linux'
EXTRACT = DATA / 'bin' / 'extract-units-linux'
FILE_UNITS = ROOT / 'experiments' / 'logic-ranker' / 'extract_units' / 'file_units.py'
MODCACHE = 'sift-planted-modcache'
QUESTION = ("Does this code enforce the caller's authorization for the resource and context "
            "it actually operates on before the protected operation?")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def ensure_volume(vol):
    if sh(['docker', 'volume', 'inspect', vol]).returncode:
        sh(['docker', 'volume', 'create', vol])
        sh(['docker', 'run', '--rm', '-v', f'{vol}:/c', 'alpine:3.20', 'chown', '1000:1000', '/c'])
    return vol


def go_env(repo):
    cfg = REPOS[repo]
    env = {'GOPROXY': 'off', 'GOTOOLCHAIN': 'local', 'HOME': '/tmp', 'GOCACHE': '/gocache',
           'GOFLAGS': cfg.get('goflags', '-mod=mod')}
    env.update(cfg.get('env', {}))
    return env


def start(repo, tree, name, cache):
    cfg = REPOS[repo]
    env = sum((['-e', f'{k}={v}'] for k, v in go_env(repo).items()), [])
    sh(['docker', 'rm', '-f', name])
    p = sh(['docker', 'run', '-d', '--name', name, '--network', 'none', '-m', cfg.get('mem', '3g'),
            '--user', '1000:1000', '-v', f'{tree}:/src', '-w', '/src',
            '-v', f'{MODCACHE}:/go/pkg/mod:ro', '-v', f'{ensure_volume(cache)}:/gocache',
            '-v', f'{PLANT}:/plant:ro', *env, cfg['image'], 'sleep', 'infinity'])
    if p.returncode:
        raise SystemExit(p.stderr)
    return name


def dexec(name, *cmd, timeout=1800):
    return sh(['docker', 'exec', name, *cmd], timeout=timeout)


def go_test(name, pkg, run=None, timeout=900):
    cmd = ['go', 'test', '-count=1', '-json', f'-timeout={timeout}s', './' + pkg]
    if run:
        cmd += ['-run', run]
    p = dexec(name, *cmd, timeout=timeout + 300)
    tests, out = {}, []
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            out.append(line)
            continue
        if ev.get('Test') and ev.get('Action') in ('pass', 'fail', 'skip'):
            tests[ev['Test']] = ev['Action']
        elif ev.get('Output'):
            out.append(ev['Output'])
    text = ''.join(out) + p.stderr
    status = 'nocompile' if re.search(r'\[build failed\]|\[setup failed\]', text) else 'ran'
    return {'status': status, 'tests': tests, 'tail': text[-3000:]}


def failing(result):
    return {t for t, a in result['tests'].items() if a == 'fail'}


def strip_names(tree, pkg, killers):
    """Map failing test paths to func/method names to delete."""
    methods, tops = set(), set()
    for f in (tree / pkg).glob('*_test.go'):
        text = f.read_text(errors='replace')
        methods |= set(re.findall(r'(?m)^func \(\s*\w*\s*\*?\w+(?:\[[^\]]*\])?\s*\) (\w+)\(', text))
        tops |= set(re.findall(r'(?m)^func (Test\w+)\(', text))
    names, via_method = set(), set()
    for k in sorted(killers):
        comps = k.split('/')
        if len(comps) == 1:
            continue
        for comp in reversed(comps[1:]):
            if comp in methods:
                names.add(comp)
                via_method.add(comps[0])
                break
        else:
            names.add(comps[0])
    for k in killers:
        if '/' not in k and k not in via_method and k in tops:
            names.add(k)
    return sorted(names)


def compile_fix(name, pkg):
    """Drop imports left unused by strip until the test package compiles."""
    for _ in range(10):
        p = dexec(name, 'go', 'test', '-count=1', '-run', '^$', './' + pkg, timeout=1800)
        errs = re.findall(r'(?m)^(\S+_test\.go):\d+:\d+: "([^"]+)" imported and not used', p.stdout + p.stderr)
        if not errs:
            return p.returncode == 0, (p.stdout + p.stderr)[-2000:]
        by_file = {}
        for f, path in errs:
            by_file.setdefault(f, set()).add(path)
        for f, paths in by_file.items():
            f = f if f.startswith('/') else '/src/' + f.removeprefix('./')
            r = dexec(name, '/plant', 'dropimport', '-file', f, '-paths', ','.join(sorted(paths)))
            if r.returncode:
                return False, r.stderr
    return False, 'import cleanup did not converge'


def strip_in(name, pkg, names):
    if not names:
        return []
    p = dexec(name, '/plant', 'strip', '-dir', '/src/' + pkg, '-names', ','.join(names))
    if p.returncode:
        raise SystemExit(p.stderr)
    return json.loads(p.stdout)


def importers(name, pkg):
    """Packages with tests that depend on pkg directly, transitively, or via test imports.

    Same top-level directory first, then by path."""
    fmt = '{{.ImportPath}}|{{.Dir}}|{{join .Deps ","}}|{{join .TestImports ","}}|{{join .XTestImports ","}}|{{len .TestGoFiles}}|{{len .XTestGoFiles}}'
    me = dexec(name, 'go', 'list', '-f', '{{.ImportPath}}', './' + pkg).stdout.strip()
    p = dexec(name, 'go', 'list', '-e', '-f', fmt, './...', timeout=3600)
    rows = {}
    for line in p.stdout.splitlines():
        parts = line.split('|')
        if len(parts) == 7:
            rows[parts[0]] = parts
    deps = {k: set(v[2].split(',')) for k, v in rows.items()}
    out = []
    for path, parts in rows.items():
        if path == me or (parts[5] == '0' and parts[6] == '0'):
            continue
        rel = str(pathlib.PurePosixPath(parts[1]).relative_to('/src'))
        if re.search(r'(^|/)(e2e|integration)(/|$)', rel):
            continue  # need a cluster or a configured server; the agent cannot run them either
        test_imports = set(parts[3].split(',')) | set(parts[4].split(','))
        if me in deps[path] or me in test_imports or any(me in deps.get(t, ()) for t in test_imports):
            out.append(rel)
    top = pkg.split('/')[0]
    return me, sorted(out, key=lambda d: (d.split('/')[0] != top, d))


def copy_tree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns('.git'))


def cmd_build(args):
    repo = args.repo
    cfg = REPOS[repo]
    kills = {json.loads(l)['id']: json.loads(l) for l in (DATA / 'pool' / repo / 'kills.jsonl').read_text().splitlines()}
    cand = {json.loads(l)['id']: json.loads(l) for l in (DATA / 'pool' / repo / 'candidates.jsonl').read_text().splitlines()}[args.id]
    kill = kills[args.id]
    if kill['status'] != 'killed':
        raise SystemExit(f'{args.id} is {kill["status"]}')
    pkg = cand['package']
    base_dir = DATA / 'cases' / args.case
    base_dir.mkdir(parents=True, exist_ok=True)
    fix, vuln = base_dir / 'fix', base_dir / 'vuln'
    log(f'{args.case}: copying {repo} trees')
    copy_tree(DATA / 'src' / repo, fix)
    baseline = json.loads((DATA / 'pool' / repo / 'baseline' / (pkg.replace('/', '__') + '.json')).read_text())
    pre_failing = failing(baseline)
    cache = f'sift-planted-gocache-{repo}'
    nf = start(repo, fix, f'sift-case-{args.case}-fix', cache)
    stripped = {}
    try:
        names = strip_names(fix, pkg, kill['killers'])
        stripped[pkg] = strip_in(nf, pkg, names)
        ok, tail = compile_fix(nf, pkg)
        if not ok:
            raise SystemExit(f'fix tree does not compile after strip:\n{tail}')
        copy_tree(fix, vuln)
        nv = start(repo, vuln, f'sift-case-{args.case}-vuln', cache)
        try:
            p = dexec(nv, '/plant', 'apply', '-root', '/src', '-id', args.id)
            if p.returncode:
                raise SystemExit(p.stderr)
            # the detecting tests are gone from both trees; nothing else may fail
            packages = [pkg]
            me, imps = importers(nf, pkg)
            log(f'{args.case}: {me} has {len(imps)} dependent packages with tests; checking {min(len(imps), args.max_importers)}')
            packages += imps[:args.max_importers]
            report = {}
            for round_ in range(3):
                changed = False
                for q in packages:
                    rv = go_test(nv, q)
                    rf = go_test(nf, q)
                    newly = sorted(failing(rv) - failing(rf))
                    report[q] = {'vuln': rv['status'], 'fix': rf['status'], 'vuln_fail': sorted(failing(rv)),
                                 'fix_fail': sorted(failing(rf)), 'detecting': newly}
                    if q == pkg and failing(rf) - pre_failing:
                        raise SystemExit(f'fix tree has new failures in {q}: {sorted(failing(rf) - pre_failing)}')
                    if newly:
                        log(f'{args.case}: {q} detects the mutation via {newly[:4]}; stripping')
                        n2 = strip_names(fix, q, newly)
                        for tree_name in (nf, nv):
                            stripped.setdefault(q, [])
                            removed = strip_in(tree_name, q, n2)
                            if tree_name == nf:
                                stripped[q] += removed
                            ok, tail = compile_fix(tree_name, q)
                            if not ok:
                                raise SystemExit(f'{q} does not compile after strip:\n{tail}')
                        changed = True
                if not changed:
                    break
            else:
                raise SystemExit('detecting tests remain after 3 rounds')
            diff = sh(['diff', '-r', '-q', str(fix), str(vuln)]).stdout.strip().splitlines()
            if diff != [f'Files {fix}/{cand["file"]} and {vuln}/{cand["file"]} differ']:
                raise SystemExit(f'trees differ beyond the mutated file: {diff[:5]}')
            log(f'{args.case}: extracting units')
            units = units_for(nv, base_dir)
            log(f'{args.case}: warming agent build cache')
            agent_cache = f'sift-planted-agentcache-{args.case}'
            sh(['docker', 'volume', 'rm', '-f', agent_cache])
            nw = start(repo, vuln, f'sift-case-{args.case}-warm', agent_cache)
            try:
                dexec(nw, 'go', 'build', './...', timeout=7200)
                dexec(nw, 'go', 'test', '-count=1', '-run', '^$', *['./' + q for q in packages], timeout=7200)
            finally:
                sh(['docker', 'rm', '-f', nw])
        finally:
            sh(['docker', 'rm', '-f', nv])
    finally:
        sh(['docker', 'rm', '-f', nf])
    meta = {
        'case': args.case, 'repo': repo, 'commit': cfg['commit'], 'image': cfg['image'],
        'goflags': cfg.get('goflags', '-mod=mod'), 'env': cfg.get('env', {}), 'mem': cfg.get('mem', '3g'),
        'mutation': {k: cand[k] for k in ('id', 'op', 'file', 'package', 'func', 'line', 'end_line', 'removed')},
        'pool_rank': kill['rank'], 'killers': kill['killers'], 'stripped': stripped,
        'checked_packages': report, 'importers_total': len(imps), 'units': units,
        'agent_cache': agent_cache, 'eval_cache': f'sift-planted-evalcache-{repo}',
        'question': QUESTION, 'built_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
    }
    (base_dir / 'case.json').write_text(json.dumps(meta, indent=2) + '\n')
    log(f'{args.case}: ok units={units} stripped={sum(len(v) for v in stripped.values())} '
        f'checked={len(packages)}/{len(imps) + 1} packages')


def units_for(name, base_dir):
    out = base_dir / 'units-raw'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    sh(['docker', 'cp', str(EXTRACT), f'{name}:/tmp/extract-units'])
    dexec(name, 'mkdir', '-p', '/tmp/units-out')
    p = dexec(name, '/tmp/extract-units', '-root', '/src', '-out', '/tmp/units-out')
    if p.returncode:
        raise SystemExit(p.stderr)
    sh(['docker', 'cp', f'{name}:/tmp/units-out/functions.jsonl', str(out / 'functions.jsonl')])
    rows = []
    for line in (out / 'functions.jsonl').read_text().splitlines():
        r = json.loads(line)
        r['file'] = str(pathlib.PurePosixPath(r['file']).relative_to('/src')) if r.get('file', '').startswith('/src') else r.get('file')
        rows.append(json.dumps(r))
    (out / 'functions.jsonl').write_text('\n'.join(rows) + '\n')
    p = sh([sys.executable, str(FILE_UNITS), '--functions', str(out / 'functions.jsonl'), '--out', str(base_dir / 'units.jsonl')])
    if p.returncode:
        raise SystemExit(p.stderr)
    return sum(1 for _ in (base_dir / 'units.jsonl').open())


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('build')
    p.add_argument('--repo', required=True); p.add_argument('--id', required=True); p.add_argument('--case', required=True)
    p.add_argument('--max-importers', type=int, default=60)
    args = ap.parse_args()
    return cmd_build(args)


if __name__ == '__main__':
    sys.exit(main())

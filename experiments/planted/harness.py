#!/usr/bin/env python3
"""Phase 2 planted-defect harness (ADR 0010).

    python3 harness.py prepare --case gitea-1 --arm vanilla|rank-bm25|rank-jev --workspace <dir> [--scope repo|topdir]
    python3 harness.py run --workspace <dir> [--max-budget-usd 30]
    python3 harness.py evaluate --workspace <dir> [--run <run.json>]
    python3 harness.py teardown --workspace <dir>

The agent reaches its container only through broker.py; it never sees the
Docker socket. Rankings are computed during prepare and charged to the run.
"""
import argparse, json, os, pathlib, re, secrets, shutil, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path('~/sift-runs/planted').expanduser()
MODEL = 'claude-mythos-5-1'
MODCACHE = 'sift-planted-modcache'
TOP_K = 10
ARMS = ('vanilla', 'rank-bm25', 'rank-jev')


def now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')
def sh(cmd, **kw): return subprocess.run(cmd, capture_output=True, text=True, **kw)


def load_case(case_id):
    meta = json.loads((DATA / 'cases' / case_id / 'case.json').read_text())
    meta['dir'] = DATA / 'cases' / case_id
    return meta


def go_env(case):
    env = {'GOPROXY': 'off', 'GOTOOLCHAIN': 'local', 'HOME': '/tmp', 'GOCACHE': '/gocache', 'GOFLAGS': case['goflags']}
    env.update(case.get('env', {}))
    return sum((['-e', f'{k}={v}'] for k, v in env.items()), [])


def volume_copy(src, dst):
    sh(['docker', 'volume', 'rm', '-f', dst])
    sh(['docker', 'volume', 'create', dst])
    p = sh(['docker', 'run', '--rm', '-v', f'{src}:/from:ro', '-v', f'{dst}:/to', 'alpine:3.20',
            'sh', '-c', 'cp -a /from/. /to/ && chown -R 1000:1000 /to'])
    if p.returncode:
        raise SystemExit(p.stderr)


def ensure_volume(vol):
    if sh(['docker', 'volume', 'inspect', vol]).returncode:
        sh(['docker', 'volume', 'create', vol])
        sh(['docker', 'run', '--rm', '-v', f'{vol}:/c', 'alpine:3.20', 'chown', '1000:1000', '/c'])
    return vol


def scope_text(case, scope):
    if scope == 'repo':
        return 'this Go project'
    top = case['mutation']['file'].split('/')[0]
    return f'the code under `{top}/` of this Go project'


def task(case, arm, scope):
    project = case['repo']
    ranking = ''
    if arm != 'vanilla':
        ranking = f"""
A file index is provided at `units.jsonl`: one row per Go source file with `id`, `target` (path), `package`, `members` and `text` (the file's functions). `RANKING.md` lists the files an automated ranker scored highest for the question above, and `ranking.tsv` has the full order (`rank<TAB>path`). A high rank is a prioritization hint, not evidence of a bug; a low rank is not evidence of safety.
"""
    return f"""# Task

Find a security-relevant authorization or access-control bug in {scope_text(case, scope)}.

Source: `src/{project}` (mounted in the container at `/src/{project}`, the module root).
Build/test: `./tb test ./path/to/pkg -run TestName` runs `go test` in the container. `./tb build ./path/...` compiles packages and their tests. `./tb exec <command...>` runs any other command in the container. The container has no network. `scratch/` is mounted at `/scratch`.

Deliver each finding under `findings/<short-name>/`:
- `report.md`: location (file and function), trigger conditions, root cause, security impact, and how you confirmed it.
- `package.txt`: the directory of the Go package your test belongs to, relative to the module root (for example `internal/service`).
- `test.go`: a Go test file in that package: top-level `func TestXxx(t *testing.T)` tests, or methods of a testify suite that the package already runs. It must fail on the vulnerable source and pass on the fixed source. It will be copied into that directory of pristine source trees for evaluation.

Rules: no network, no external reports. Keep scratch files under `scratch/`.

Question to keep in mind (the same text is given in every setup):

> {case['question']}
{ranking}"""


def ranking_md(rows):
    lines = '\n'.join(f'{r}. `{p}`' for r, p in rows[:TOP_K])
    return f"""# File ranking

An automated ranker scored every file in `units.jsonl` for the question in TASK.md. These are its top {TOP_K}. The full order is in `ranking.tsv`.

{lines}

Use the ranking to decide where to look first. It is not evidence of a bug, and a low rank is not evidence of safety. The source is the ground truth.
"""


def settings(ws, broker_sock):
    return {
        'permissions': {
            'deny': ['WebFetch', 'WebSearch', 'Bash(docker *)', 'Bash(curl *)', 'Bash(wget *)'],
            'blockReadsOutsideWorkingDirectories': True,
        },
        'sandbox': {
            'enabled': True, 'autoAllowBashIfSandboxed': True,
            'network': {'strictAllowlist': True, 'allowedDomains': [], 'allowUnixSockets': [str(broker_sock)]},
            'filesystem': {'denyRead': [str(ws.parent), str(ws / 'control')], 'allowRead': [str(ws / 'agent')]},
        },
    }


def cmd_prepare(args):
    case = load_case(args.case)
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    if ws.exists() and any(ws.iterdir()):
        raise SystemExit(f'workspace is not empty: {ws}')
    agent, control = ws / 'agent', ws / 'control'
    (agent / 'findings').mkdir(parents=True)
    (agent / 'scratch').mkdir()
    control.mkdir()
    src = agent / 'src' / case['repo']
    shutil.copytree(case['dir'] / 'vuln', src, symlinks=True)
    prep = {'started_at': now()}
    t0 = time.monotonic()
    rank_stats = None
    if args.arm != 'vanilla':
        shutil.copy(case['dir'] / 'units.jsonl', agent / 'units.jsonl')
        ranker = args.arm.removeprefix('rank-')
        cmd = [sys.executable, str(HERE / 'rank.py'), '--units', str(case['dir'] / 'units.jsonl'),
               '--ranker', ranker, '--out', str(control / 'ranking.tsv'), '--calls', str(control / 'jev-calls.jsonl')]
        p = sh(cmd)
        if p.returncode:
            raise SystemExit(p.stderr)
        rank_stats = json.loads(p.stdout.strip().splitlines()[-1])
        if rank_stats.get('errors'):
            print(f"warn {rank_stats['errors']} unscored units")
        shutil.copy(control / 'ranking.tsv', agent / 'ranking.tsv')
        rows = [l.split('\t') for l in (control / 'ranking.tsv').read_text().splitlines()]
        (agent / 'RANKING.md').write_text(ranking_md([(int(r), p) for r, p in rows]))
        mut = case['mutation']['file']
        prep['mutated_file_rank'] = next((int(r) for r, p in rows if p == mut), None)
    prep['ranking'] = rank_stats
    prep['ranking_seconds'] = round(time.monotonic() - t0, 1)
    name = f'sift-p2-{secrets.token_hex(4)}'
    cache = f'sift-p2-cache-{name}'
    volume_copy(case['agent_cache'], cache)
    mount = f"/src/{case['repo']}"
    p = sh(['docker', 'run', '-d', '--name', name, '--network', 'none', '-m', case['mem'], '--user', '1000:1000',
            '-v', f'{src}:{mount}', '-v', f'{agent / "scratch"}:/scratch',
            '-v', f'{MODCACHE}:/go/pkg/mod:ro', '-v', f'{cache}:/gocache', *go_env(case),
            '-w', mount, case['image'], 'sleep', 'infinity'])
    if p.returncode:
        raise SystemExit(p.stderr)
    sock = control / 'tb.sock'
    broker = subprocess.Popen([sys.executable, str(HERE / 'broker.py'), '--socket', str(sock), '--container', name,
                               '--workdir', mount, '--log', str(control / 'broker.jsonl')],
                              stdout=subprocess.DEVNULL, stderr=open(control / 'broker.err', 'w'))
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.1)
    if not sock.exists():
        raise SystemExit('broker did not start')
    shutil.copy(HERE / 'tb_client.py', agent / '.tb_client.py')
    (agent / 'tb').write_text(f'#!/bin/sh\nexport TB_SOCKET="{sock}"\nexec python3 "{agent / ".tb_client.py"}" "$@"\n')
    (agent / 'tb').chmod(0o755)
    (agent / 'TASK.md').write_text(task(case, args.arm, args.scope))
    (control / 'claude-settings.json').write_text(json.dumps(settings(ws, sock), indent=2) + '\n')
    prep['finished_at'] = now()
    (control / 'workspace.json').write_text(json.dumps({
        'case': args.case, 'arm': args.arm, 'scope': args.scope, 'container': name, 'cache_volume': cache,
        'broker_pid': broker.pid, 'prepare': prep, 'created_at': now(),
    }, indent=2) + '\n')
    print(f'ok   {ws} case={args.case} arm={args.arm} scope={args.scope} container={name} '
          f'rank={prep.get("mutated_file_rank")} jev=${(rank_stats or {}).get("cost_usd", 0)}')


def parse_stream(path):
    results, tools, models, assistant_turns = [], [], set(), 0
    for line in path.read_text(errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get('type') == 'assistant':
            msg = ev.get('message') or {}
            assistant_turns += 1
            if msg.get('model'):
                models.add(msg['model'])
            for block in msg.get('content') or []:
                if block.get('type') == 'tool_use':
                    tools.append({'turn': assistant_turns, 'name': block.get('name'), 'input': block.get('input') or {}})
        if ev.get('type') == 'result':
            results.append({k: ev.get(k) for k in ('subtype', 'is_error', 'total_cost_usd', 'duration_ms', 'num_turns', 'usage',
                                                   'terminal_reason')} | {'result': str(ev.get('result') or '')[:500]})
    main = results[-1] if results else None
    costs = [r['total_cost_usd'] for r in results if isinstance(r.get('total_cost_usd'), (int, float))]
    return main, tools, sorted(models), max(costs) if costs else None, assistant_turns


LIMIT = re.compile(r"hit your (session|usage|weekly) limit|rate limit|overloaded|credit balance", re.I)


def infra_abort(main):
    if main is None:
        return 'no result event'
    if main.get('terminal_reason') == 'api_error' or (main.get('is_error') and LIMIT.search(main.get('result') or '')):
        return (main.get('result') or main.get('terminal_reason') or 'api error')[:200]
    return None


def first_touch(tools, rel):
    base = rel.rsplit('/', 1)[-1]
    first_mention = first_read = None
    for t in tools:
        text = json.dumps(t['input'])
        if base in text and first_mention is None:
            first_mention = t['turn']
        reading = (t['name'] == 'Read' and str(t['input'].get('file_path', '')).endswith(rel)) or (
            t['name'] == 'Bash' and base in str(t['input'].get('command', ''))
            and re.search(r'(^|[\s|;&(])(cat|sed|nl|head|tail|less|awk|bat)\s', str(t['input'].get('command', ''))))
        if reading and first_read is None:
            first_read = t['turn']
    return first_mention, first_read


def audit(tools):
    cmds = [str(t['input'].get('command', '')) for t in tools if t['name'] == 'Bash']
    return {
        'docker': sum(1 for c in cmds if re.search(r'(^|[^\w./-])docker(\s|$)|docker\.sock', c)),
        'network': sum(1 for c in cmds if re.search(r'(^|[\s;&|])(curl|wget|nc|ssh|scp)(\s|$)', c)),
        'subagent': sum(1 for t in tools if t['name'] in ('Task', 'Agent')),
        'parent_path': sum(1 for c in cmds if '../' in c),
    }


def cmd_run(args):
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    meta = json.loads((ws / 'control' / 'workspace.json').read_text())
    case = load_case(meta['case'])
    if sh(['docker', 'inspect', '--format', '{{.State.Running}}', meta['container']]).stdout.strip() != 'true':
        raise SystemExit('container is not running')
    run_dir = ws / 'control' / 'runs' / time.strftime('%Y%m%dT%H%M%S')
    run_dir.mkdir(parents=True)
    rank_cost = ((meta['prepare'].get('ranking') or {}).get('cost_usd') or 0.0)
    claude_cap = max(0.0, args.max_budget_usd - rank_cost)
    cmd = ['claude', '-p', (ws / 'agent' / 'TASK.md').read_text(),
           '--settings', str(ws / 'control' / 'claude-settings.json'),
           '--setting-sources', 'project', '--disable-slash-commands', '--strict-mcp-config',
           '--model', args.model, '--effort', args.effort, '--permission-mode', 'acceptEdits',
           '--output-format', 'stream-json', '--verbose', '--max-budget-usd', f'{claude_cap:.6f}',
           '--disallowedTools', 'Task', 'Agent']
    record = {'case': meta['case'], 'arm': meta['arm'], 'scope': meta['scope'], 'model_requested': args.model,
              'effort': args.effort, 'cap_usd': args.max_budget_usd, 'claude_cap_usd': round(claude_cap, 6),
              'rank_cost_usd': rank_cost, 'ranking_seconds': meta['prepare'].get('ranking_seconds', 0.0),
              'mutated_file_rank': meta['prepare'].get('mutated_file_rank'),
              'claude_version': sh(['claude', '--version']).stdout.strip(),
              'started_at': now(), 'args': cmd[3:]}
    print(f'run {meta["case"]} arm={meta["arm"]} model={args.model} cap=${args.max_budget_usd} claude_cap=${claude_cap:.3f}', flush=True)
    t0 = time.monotonic()
    with open(run_dir / 'stream.jsonl', 'wb') as out, open(run_dir / 'stderr.log', 'wb') as err:
        proc = subprocess.Popen(cmd, cwd=ws / 'agent', stdout=out, stderr=err)
        proc.wait()
    record['elapsed_seconds'] = round(time.monotonic() - t0, 1)
    record['exit_code'] = proc.returncode
    main, tools, models, claude_cost, turns = parse_stream(run_dir / 'stream.jsonl')
    abort = infra_abort(main)
    if abort:
        # a session limit or API failure is not the agent's outcome; the run is redone
        record.update({'result': main, 'claude_cost_usd': claude_cost, 'infra_abort': abort, 'valid': False})
        (run_dir / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
        print(f'abort infra: {abort} claude=${claude_cost} record={run_dir / "run.json"}', flush=True)
        return 3
    mut = case['mutation']['file']
    mention, read = first_touch(tools, mut)
    record.update({'result': main, 'claude_cost_usd': claude_cost, 'models_seen': models, 'tool_calls': len(tools),
                   'assistant_messages': turns, 'num_turns': (main or {}).get('num_turns'),
                   'audit': audit(tools), 'mutated_first_mention_turn': mention, 'mutated_first_read_turn': read,
                   'broker_calls': sum(1 for _ in (ws / 'control' / 'broker.jsonl').open()) if (ws / 'control' / 'broker.jsonl').exists() else 0})
    (run_dir / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
    shutil.copytree(ws / 'agent' / 'findings', run_dir / 'findings')
    record = evaluate_run(ws, case, run_dir, record, args.max_budget_usd)
    print(f'done claude=${claude_cost} rank=${rank_cost} total=${record["total_cost_usd"]} turns={record["num_turns"]} '
          f'technical={record["evaluation"]["verdict"]} valid={record["valid"]} first_read={read}', flush=True)
    print(f'     audit={record["audit"]} record={run_dir / "run.json"}')
    return 0 if record['valid'] else 2


def add_decoy(root, pkg):
    target = root / pkg
    go_files = sorted(p for p in target.glob('*.go') if not p.name.endswith('_test.go'))
    if go_files:
        go_files[0].write_text(go_files[0].read_text(errors='replace') + '\n\nvar _ = 0 // unrelated decoy change\n')
        return
    name = 'main'
    for p in target.glob('*_test.go'):
        m = re.search(r'(?m)^package (\w+)', p.read_text(errors='replace'))
        if m:
            name = m.group(1).removesuffix('_test')
            break
    (target / 'zz_decoy.go').write_text(f'package {name}\n\nvar _ = 0\n')


def go_test_tree(case, root, pkg, run_re):
    p = sh(['docker', 'run', '--rm', '--network', 'none', '-m', case['mem'], '--user', '1000:1000',
            '-v', f'{root}:/src/{case["repo"]}', '-w', f'/src/{case["repo"]}',
            '-v', f'{MODCACHE}:/go/pkg/mod:ro', '-v', f'{ensure_volume(case["eval_cache"])}:/gocache', *go_env(case),
            case['image'], 'timeout', '-s', 'KILL', '1500', 'go', 'test', '-json', './' + pkg, '-run', run_re, '-count=1'],
           timeout=1800)
    tests, out = {}, []
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            out.append(line + '\n')
            continue
        if ev.get('Test') and ev.get('Action') in ('pass', 'fail', 'skip'):
            tests[ev['Test']] = ev['Action']
        if ev.get('Output'):
            out.append(ev['Output'])
    text = ''.join(out) + p.stderr
    return {'exit': p.returncode, 'tests': tests, 'tail': text[-3000:],
            'compile_error': bool(re.search(r'(?m)^# |\[build failed\]|\[setup failed\]', text)),
            'panic': bool(re.search(r'(?m)^panic: |test panicked', text))}


TOP_TEST = re.compile(r'(?m)^func\s+(Test\w+)\s*\(\s*\w+\s+\*testing\.T\s*\)')
SUITE_METHOD = re.compile(r'(?m)^func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(Test\w+)\s*\(\s*\)')
RUNNER = re.compile(r'(?ms)^func\s+(Test\w+)\s*\(\s*(\w+)\s+\*testing\.T\s*\)\s*\{(.*?)^\}')


def selectors(pkg_dir, text):
    """Groups of (go test -run pattern, expected test names) for a submitted file."""
    groups = []
    tops = TOP_TEST.findall(text)
    if tops:
        groups.append(('^(' + '|'.join(sorted(set(tops))) + ')$', sorted(set(tops))))
    methods = {}
    for recv, name in SUITE_METHOD.findall(text):
        methods.setdefault(recv, set()).add(name)
    sources = [text] + [f.read_text(errors='replace') for f in sorted(pkg_dir.glob('*_test.go'))]
    for recv, names in sorted(methods.items()):
        runner = None
        for src in sources:
            for fn, _, body in RUNNER.findall(src):
                if re.search(r'suite\.Run\(\s*\w+\s*,\s*(new\(\s*' + recv + r'\s*\)|&' + recv + r'\s*\{)', body):
                    runner = fn
                    break
            if runner:
                break
        if runner and runner not in tops:
            pat = '^' + runner + '$/^(' + '|'.join(sorted(names)) + ')$'
            groups.append((pat, sorted(f'{runner}/{n}' for n in names)))
    return groups


SOURCE_READ = re.compile(r'(os\.ReadFile|ioutil\.ReadFile|os\.Open|os\.ReadDir|filepath\.Walk)\([^)]*\.go\b|"go/(parser|ast|token)"')


def evaluate_finding(ws, case, finding, tag):
    test = finding / 'test.go'
    pkg_file = finding / 'package.txt'
    out = {'finding': finding.name}
    if not test.exists() or not pkg_file.exists():
        out.update(verdict='incomplete', reason='test.go or package.txt missing')
        return out
    pkg = pkg_file.read_text().strip().strip('/').removeprefix('./')
    out['package'] = pkg
    if not pkg or '..' in pkg.split('/') or not (case['dir'] / 'vuln' / pkg).is_dir():
        out.update(verdict='rejected', reason=f'package directory not found: {pkg!r}')
        return out
    text = test.read_text(errors='replace')
    groups = selectors(case['dir'] / 'vuln' / pkg, text)
    out['tests'] = [n for _, names in groups for n in names]
    out['source_read'] = bool(SOURCE_READ.search(text))
    if not groups:
        out.update(verdict='rejected', reason='no runnable Test function or suite method')
        return out
    base = ws / 'control' / 'eval' / tag
    if base.exists():
        shutil.rmtree(base)
    runs = {}
    for mode, source in (('vuln', 'vuln'), ('fix', 'fix'), ('decoy', 'vuln')):
        root = base / mode
        shutil.copytree(case['dir'] / source, root, symlinks=True)
        if mode == 'decoy':
            add_decoy(root, pkg)
        shutil.copy(test, root / pkg / f'agent_finding_{tag}_test.go')
        reps = []
        for _ in range(3):
            parts = [(go_test_tree(case, root, pkg, pat), names) for pat, names in groups]
            reps.append({
                'compile_error': any(r['compile_error'] for r, _ in parts),
                'panic': any(r['panic'] for r, _ in parts),
                'tests': {n: r['tests'].get(n, 'missing') for r, names in parts for n in names},
                'tail': '\n'.join(r['tail'][-1500:] for r, _ in parts),
            })
        runs[mode] = reps
    shutil.rmtree(base)
    detects = lambda rs: all(not r['compile_error'] and not r['panic'] and 'fail' in r['tests'].values() for r in rs)
    out['runs'] = runs
    out['vuln_ok'] = detects(runs['vuln'])
    out['fix_ok'] = all(not r['compile_error'] and not r['panic'] and set(r['tests'].values()) == {'pass'} for r in runs['fix'])
    out['decoy_ok'] = detects(runs['decoy'])
    out['verdict'] = 'reproduced' if out['vuln_ok'] and out['fix_ok'] and out['decoy_ok'] else 'rejected'
    report = (finding / 'report.md').read_text(errors='replace') if (finding / 'report.md').exists() else ''
    mut = case['mutation']['file']
    out['has_report'] = bool(report.strip())
    out['names_mutated_file'] = mut in report or mut.rsplit('/', 1)[-1] in report
    return out


def evaluate_run(ws, case, run_dir, record, cap):
    findings = sorted(p for p in (run_dir / 'findings').iterdir() if p.is_dir()) if (run_dir / 'findings').exists() else []
    evals = [evaluate_finding(ws, case, f, str(i)) for i, f in enumerate(findings)]
    good = [e for e in evals if e.get('verdict') == 'reproduced' and e.get('names_mutated_file') and not e.get('source_read')]
    record['evaluation'] = {'findings': evals, 'verdict': 'reproduced' if any(e.get('verdict') == 'reproduced' for e in evals)
                            else ('no-finding' if not evals else 'rejected'),
                            'valid_findings': [e['finding'] for e in good]}
    total = round((record.get('claude_cost_usd') or cap) + record.get('rank_cost_usd', 0.0), 6)
    a = record['audit']
    record['total_cost_usd'] = total
    record['audit_clean'] = not (a['docker'] or a['network'] or a['subagent'])
    record['within_cap'] = total <= cap + 1e-9
    record['valid'] = bool(good) and record['audit_clean'] and record['within_cap'] and record.get('claude_cost_usd') is not None
    (run_dir / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def cmd_evaluate(args):
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    meta = json.loads((ws / 'control' / 'workspace.json').read_text())
    case = load_case(meta['case'])
    run_json = pathlib.Path(args.run) if args.run else sorted((ws / 'control' / 'runs').glob('*/run.json'))[-1]
    record = json.loads(run_json.read_text())
    record = evaluate_run(ws, case, run_json.parent, record, record['cap_usd'])
    print(f'evaluated {run_json} technical={record["evaluation"]["verdict"]} valid={record["valid"]}')


def cmd_teardown(args):
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    meta = json.loads((ws / 'control' / 'workspace.json').read_text())
    sh(['docker', 'rm', '-f', meta['container']])
    sh(['docker', 'volume', 'rm', '-f', meta['cache_volume']])
    try:
        os.kill(meta['broker_pid'], 15)
    except ProcessLookupError:
        pass
    print(f'ok   teardown {ws}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--case', required=True); p.add_argument('--arm', choices=ARMS, required=True)
    p.add_argument('--workspace', required=True); p.add_argument('--scope', choices=('repo', 'topdir'), default='repo')
    p = sub.add_parser('run'); p.add_argument('--workspace', required=True); p.add_argument('--model', default=MODEL)
    p.add_argument('--effort', default='high'); p.add_argument('--max-budget-usd', type=float, default=30.0)
    p = sub.add_parser('evaluate'); p.add_argument('--workspace', required=True); p.add_argument('--run')
    p = sub.add_parser('teardown'); p.add_argument('--workspace', required=True)
    args = ap.parse_args()
    return {'prepare': cmd_prepare, 'run': cmd_run, 'evaluate': cmd_evaluate, 'teardown': cmd_teardown}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())

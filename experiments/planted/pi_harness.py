#!/usr/bin/env python3
"""Run the planted-defect task with Pi and a non-Claude model.

    python3 pi_harness.py run --workspace <dir> [--max-tokens 3000000]
    python3 pi_harness.py evaluate --workspace <dir> [--run <run.json>]
    python3 pi_harness.py reparse --workspace <dir>

`prepare` and `teardown` are shared with harness.py. The Pi process runs on
the host; its bash tool forwards to the same broker and therefore executes
inside the case container. File tools are confined to the workspace by the
Pi extension in pi_runner/agent_ext.ts.
"""
import argparse, json, os, pathlib, re, shutil, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness

MODEL = 'ollama-cloud/deepseek-v4.1-flash:1017'
THINKING = 'medium'
TOOLS = 'read,write,edit,grep,find,ls,bash'
EXT = HERE / 'pi_runner' / 'agent_ext.ts'


def now(): return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def pi_task(case, arm, scope):
    return harness.task(case, arm, scope) + f"""

## Pi runner note

- `read`, `write`, `edit`, `grep`, `find`, `ls` see the workspace: source is at `src/{case['repo']}/...`.
- `bash` runs inside the case container with the module root as its current directory. Use paths such as `pkg/...`; `scratch/` maps to `/scratch/`.
- `./tb test|build|exec` is supported and translated. The container has no network.
- Do not inspect `/gocache`, `/go/pkg/mod`, compiled archives, or build metadata. They are not evidence and waste budget. Read the source.
"""


def parse_stream(path):
    """Parse Pi's JSON event stream. Usage is summed over assistant messages."""
    turns = 0
    usage = {k: 0 for k in ('input', 'output', 'cacheRead', 'cacheWrite', 'reasoning', 'totalTokens')}
    cost = 0.0
    tools, models, stops, errors = [], set(), [], []
    aborted = False
    for line in path.read_text(errors='replace').splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get('type')
        if t == 'message_end':
            msg = ev.get('message') or {}
            if msg.get('role') != 'assistant':
                continue
            turns += 1
            if msg.get('model'):
                models.add(msg['model'])
            u = msg.get('usage') or {}
            for k in usage:
                usage[k] += int(u.get(k) or 0)
            c = u.get('cost') or {}
            cost += float(c.get('total') or 0.0)
            stop = msg.get('stopReason')
            if stop:
                stops.append(stop)
            if msg.get('errorMessage'):
                errors.append(str(msg['errorMessage']))
        elif t == 'tool_execution_start':
            tools.append({'turn': turns, 'name': ev.get('toolName'), 'input': ev.get('args') or {}})
        elif t == 'auto_retry_end' and ev.get('success') is False:
            errors.append(str(ev.get('finalError') or 'auto retry failed'))
        elif t == 'agent_settled':
            aborted = bool(ev.get('aborted'))
    error_text = '; '.join(dict.fromkeys(errors))
    terminal = 'api_error' if harness.LIMIT.search(error_text) else ('aborted' if aborted else 'completed')
    is_error = bool(errors) or aborted
    main = {
        'subtype': 'error' if is_error else 'success',
        'is_error': is_error,
        'total_cost_usd': None,
        'num_turns': turns,
        'usage': usage,
        'terminal_reason': terminal,
        'result': error_text[:500],
    }
    return {
        'main': main,
        'usage': usage,
        'provider_cost_usd': round(cost, 6),
        'models': sorted(models),
        'stop_reasons': stops,
        'errors': errors,
        'aborted': aborted,
        'num_turns': turns,
        'tool_calls': tools,
    }


def first_touch(tools, rel):
    base = rel.rsplit('/', 1)[-1]
    first_mention = first_read = None
    for t in tools:
        text = json.dumps(t['input'])
        if base in text and first_mention is None:
            first_mention = t['turn']
        path_arg = str(t['input'].get('path', ''))
        reading = (t['name'] == 'read' and path_arg.endswith(rel)) or (
            t['name'] == 'bash' and base in str(t['input'].get('command', ''))
            and re.search(r'(^|[\s|;&(])(cat|sed|nl|head|tail|less|awk|bat)\s', str(t['input'].get('command', '')))
        )
        if reading and first_read is None:
            first_read = t['turn']
    return first_mention, first_read


def evaluate_pi(ws, case, run_dir, record, cap_tokens):
    findings = sorted(p for p in (run_dir / 'findings').iterdir() if p.is_dir()) if (run_dir / 'findings').exists() else []
    evals = [harness.evaluate_finding(ws, case, f, str(i)) for i, f in enumerate(findings)]
    good = [e for e in evals if e.get('verdict') == 'reproduced' and e.get('names_mutated_file') and not e.get('source_read')]
    record['evaluation'] = {
        'findings': evals,
        'verdict': 'reproduced' if any(e.get('verdict') == 'reproduced' for e in evals)
        else ('no-finding' if not evals else 'rejected'),
        'valid_findings': [e['finding'] for e in good],
    }
    total = int(record.get('usage', {}).get('totalTokens') or 0)
    if record.get('cap_hit'):
        total = max(total, int(cap_tokens or 0))
    a = record['audit']
    record['total_tokens'] = total
    record['cap_tokens'] = cap_tokens
    record['cost_basis'] = 'tokens'
    record['audit_clean'] = not (a['docker'] or a['network'] or a['subagent'])
    record['within_cap'] = (not record.get('cap_hit')) and (total <= cap_tokens + 1e-9 if cap_tokens else True)
    record['valid'] = bool(good) and record['audit_clean'] and record['within_cap'] and total > 0
    (run_dir / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def collect_findings(ws, case, run_dir):
    """bash writes findings under the container's module root, which is the
    host copy at agent/src/<repo>/; the write/edit tools write to agent/findings.
    Merge both into the run directory."""
    host = ws / 'agent' / 'findings'
    src = ws / 'agent' / 'src' / case['repo'] / 'findings'
    if src.exists():
        shutil.copytree(src, host, dirs_exist_ok=True)
    if host.exists():
        shutil.copytree(host, run_dir / 'findings', dirs_exist_ok=True)


def cmd_run(args):
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    meta = json.loads((ws / 'control' / 'workspace.json').read_text())
    case = harness.load_case(meta['case'])
    if harness.sh(['docker', 'inspect', '--format', '{{.State.Running}}', meta['container']]).stdout.strip() != 'true':
        raise SystemExit('container is not running')
    run_dir = ws / 'control' / 'runs' / time.strftime('%Y%m%dT%H%M%S')
    run_dir.mkdir(parents=True)
    task = pi_task(case, meta['arm'], meta['scope'])
    (ws / 'control' / 'TASK.pi.md').write_text(task)
    rank = meta['prepare'].get('ranking') or {}
    record = {
        'runner': 'pi',
        'case': meta['case'], 'arm': meta['arm'], 'scope': meta['scope'],
        'model_requested': args.model, 'thinking': args.thinking, 'cap_tokens': args.max_tokens,
        'rank_cost_usd': rank.get('cost_usd') or 0.0,
        'jev_input_tokens': rank.get('input_tokens') or 0,
        'ranking_seconds': meta['prepare'].get('ranking_seconds', 0.0),
        'mutated_file_rank': meta['prepare'].get('mutated_file_rank'),
        'pi_version': harness.sh(['pi', '--version']).stdout.strip(),
        'started_at': now(),
    }
    cmd = [
        'pi', '--mode', 'json', '--no-session', '--no-context-files', '--no-skills',
        '--no-prompt-templates', '--no-themes', '--no-mcp', '--no-approve',
        '--tools', TOOLS, '--model', args.model, '--thinking', args.thinking,
        '-e', str(EXT), task,
    ]
    record['args'] = cmd[:-1]
    print(f'run pi {meta["case"]} arm={meta["arm"]} model={args.model} cap_tokens={args.max_tokens}', flush=True)
    env = dict(os.environ)
    env['TB_SOCKET'] = str(ws / 'control' / 'tb.sock')
    env['PI_CASE_REPO'] = case['repo']
    env['NO_COLOR'] = '1'
    t0 = time.monotonic()
    cap_hit = False
    wall_timeout = False
    tokens = 0
    with open(run_dir / 'stream.jsonl', 'w') as out, open(run_dir / 'stderr.log', 'w') as err:
        proc = subprocess.Popen(cmd, cwd=ws / 'agent', stdout=subprocess.PIPE, stderr=err,
                                text=True, bufsize=1, env=env)
        assert proc.stdout is not None
        for line in proc.stdout:
            out.write(line)
            out.flush()
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get('type') == 'message_end':
                msg = ev.get('message') or {}
                if msg.get('role') == 'assistant':
                    tokens += int((msg.get('usage') or {}).get('totalTokens') or 0)
            if time.monotonic() - t0 > args.wall_timeout:
                wall_timeout = True
                proc.terminate()
                break
            if args.max_tokens and tokens > args.max_tokens:
                cap_hit = True
                proc.terminate()
                break
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    record['elapsed_seconds'] = round(time.monotonic() - t0, 1)
    record['exit_code'] = proc.returncode
    st = parse_stream(run_dir / 'stream.jsonl')
    record.update({
        'usage': st['usage'],
        'provider_cost_usd': st['provider_cost_usd'],
        'models_seen': st['models'],
        'stop_reasons': st['stop_reasons'],
        'errors': st['errors'],
        'aborted': st['aborted'],
        'num_turns': st['num_turns'],
        'tool_calls': len(st['tool_calls']),
        'cap_hit': cap_hit,
        'wall_timeout': wall_timeout,
        'audit': harness.audit(st['tool_calls']),
    })
    mention, read = first_touch(st['tool_calls'], case['mutation']['file'])
    record['mutated_first_mention_turn'] = mention
    record['mutated_first_read_turn'] = read
    record['broker_calls'] = sum(1 for _ in (ws / 'control' / 'broker.jsonl').open()) if (ws / 'control' / 'broker.jsonl').exists() else 0
    abort = harness.infra_abort(st['main'])
    if abort is None and wall_timeout:
        abort = 'wall timeout'
    if abort is None and proc.returncode != 0 and st['num_turns'] == 0 and not cap_hit:
        tail = (run_dir / 'stderr.log').read_text(errors='replace').strip().splitlines()
        abort = f'pi exited {proc.returncode}: {tail[-1] if tail else "no stderr"}'[:200]
    if abort:
        record.update({'infra_abort': abort, 'valid': False})
        (run_dir / 'run.json').write_text(json.dumps(record, indent=2) + '\n')
        print(f'abort infra: {abort} tokens={record["usage"]["totalTokens"]} record={run_dir / "run.json"}', flush=True)
        return 3
    collect_findings(ws, case, run_dir)
    record = evaluate_pi(ws, case, run_dir, record, args.max_tokens)
    print(f'done tokens={record["total_tokens"]} turns={record["num_turns"]} '
          f'technical={record["evaluation"]["verdict"]} valid={record["valid"]} first_read={read}', flush=True)
    print(f'     audit={record["audit"]} record={run_dir / "run.json"}', flush=True)
    return 0 if record['valid'] else 2


def cmd_evaluate(args):
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    meta = json.loads((ws / 'control' / 'workspace.json').read_text())
    case = harness.load_case(meta['case'])
    run_json = pathlib.Path(args.run) if args.run else sorted((ws / 'control' / 'runs').glob('*/run.json'))[-1]
    record = json.loads(run_json.read_text())
    record = evaluate_pi(ws, case, run_json.parent, record, record.get('cap_tokens'))
    print(f'evaluated {run_json} technical={record["evaluation"]["verdict"]} valid={record["valid"]}')


def cmd_reparse(args):
    ws = pathlib.Path(args.workspace).expanduser().resolve()
    meta = json.loads((ws / 'control' / 'workspace.json').read_text())
    case = harness.load_case(meta['case'])
    for run_json in sorted((ws / 'control' / 'runs').glob('*/run.json')):
        record = json.loads(run_json.read_text())
        st = parse_stream(run_json.parent / 'stream.jsonl')
        mention, read = first_touch(st['tool_calls'], case['mutation']['file'])
        record.update({
            'usage': st['usage'], 'provider_cost_usd': st['provider_cost_usd'],
            'models_seen': st['models'], 'stop_reasons': st['stop_reasons'], 'errors': st['errors'],
            'aborted': st['aborted'], 'num_turns': st['num_turns'], 'tool_calls': len(st['tool_calls']),
            'audit': harness.audit(st['tool_calls']),
            'mutated_first_mention_turn': mention, 'mutated_first_read_turn': read,
        })
        run_json.write_text(json.dumps(record, indent=2) + '\n')
        print(f'reparsed {run_json} tokens={record["usage"]["totalTokens"]} turns={record["num_turns"]}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('run'); p.add_argument('--workspace', required=True)
    p.add_argument('--model', default=MODEL); p.add_argument('--thinking', default=THINKING)
    p.add_argument('--max-tokens', type=int, default=3_000_000); p.add_argument('--wall-timeout', type=int, default=7200)
    p = sub.add_parser('evaluate'); p.add_argument('--workspace', required=True); p.add_argument('--run')
    p = sub.add_parser('reparse'); p.add_argument('--workspace', required=True)
    args = ap.parse_args()
    return {'run': cmd_run, 'evaluate': cmd_evaluate, 'reparse': cmd_reparse}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())

"""Measure whether sink slices contain Magma changed lines, without calling a model.

Run from the boilerplate environment:

    cd boilerplate
    uv run python ../experiments/second-pass/magma_slice_recall.py libpng \
      --output ../data/magma-2026-09-29/slice-recall-libpng.json

This is a bounded structural gate, not an end-to-end vulnerability-discovery result.
"""

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from bench.magma.scan import changed_lines  # noqa: E402
from sift import cfamily, dataflow, slices  # noqa: E402

BUDGETS = (4_000, 8_000, 16_000)
TARGETS = ("libpng", "libtiff", "libxml2")


def json_lines(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSONL input {path}: {error}") from error


def relocated_compile_db(source: Path, destination: Path) -> Path:
    """Copy a historical compile DB while relocating only its vanished build directory."""
    try:
        entries = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read compile database {source}: {error}") from error
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"compile database is empty or not a list: {source}")
    current = str(source.parent.resolve())
    old = {entry.get("directory") for entry in entries if isinstance(entry, dict)}
    old.discard(None)
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ValueError(f"invalid compile database entry in {source}")
        for prefix in old:
            for key in ("directory", "command"):
                if isinstance(entry.get(key), str):
                    entry[key] = entry[key].replace(prefix, current)
            if isinstance(entry.get("arguments"), list):
                entry["arguments"] = [a.replace(prefix, current) if isinstance(a, str) else a
                                      for a in entry["arguments"]]
    destination.write_text(json.dumps(entries))
    return destination


def covered_lines(slice_) -> set[tuple[str, int]]:
    return {(span.path, line) for span in slice_.spans
            for line in range(span.start_line, span.end_line + 1)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--data", type=Path, default=REPO / "data/magma-2026-09-29")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument(
        "--sink-functions",
        choices=("scope", "labels"),
        default="scope",
        help="use all in-scope sinks, or the optimistic upper bound of sinks in labeled functions",
    )
    args = parser.parse_args()

    target = args.target
    root = REPO / f"targets/magma-src/{target}-bugs"
    run_dir = args.data / f"runs/{target}"
    db = args.data / f"db/{target}/compile_commands.json"
    if not root.is_dir():
        parser.error(f"target tree does not exist: {root}")
    scope_rows = json_lines(run_dir / "functions.jsonl")
    scope_ids = {row.get("id") for row in scope_rows}
    if None in scope_ids or not scope_ids:
        parser.error(f"function scope is empty or malformed: {run_dir / 'functions.jsonl'}")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"sift-{target}-db-") as temporary:
        local_db = relocated_compile_db(db, Path(temporary) / "compile_commands.json")
        print(f"scanning {target} with dataflow...", file=sys.stderr, flush=True)
        scan = cfamily.scan(root, [local_db], workers=args.workers, dataflow=True)
    scan_seconds = time.monotonic() - started

    found_ids = {function.id for function in scan.functions}
    missing_scope = sorted(scope_ids - found_ids)
    if missing_scope:
        raise RuntimeError(f"current scan missed {len(missing_scope)} functions from the frozen scope; "
                           f"first: {missing_scope[:5]}")

    print("building whole-program summaries...", file=sys.stderr, flush=True)
    built_at = time.monotonic()
    program = dataflow.program(scan, root)
    program_seconds = time.monotonic() - built_at
    all_sinks = slices.sinks(program)
    labels = json.loads((args.data / f"labels-{target}.json").read_text())
    changes = changed_lines(target)
    if set(labels) != set(changes):
        raise RuntimeError("function labels and changed-line labels name different bugs")
    label_function_ids = set().union(*(set(ids) for ids in labels.values()))
    sink_function_ids = scope_ids if args.sink_functions == "scope" else label_function_ids
    selected_sinks = [sink for sink in all_sinks if sink.function in sink_function_ids]

    per_budget = {budget: {"packets": {}, "tokens": 0} for budget in BUDGETS}
    per_bug = {
        bug: {
            str(budget): {
                "changed_line_slices": 0,
                "label_context_slices": 0,
                "sink_in_label_function_slices": 0,
                "changed_line_and_label_sink_slices": 0,
                "sink_ids": [],
            }
            for budget in BUDGETS
        }
        for bug in sorted(labels)
    }
    label_sets = {bug: set(ids) for bug, ids in labels.items()}
    changed_sets = {bug: {tuple(place) for place in changes[bug]} for bug in labels}

    print(f"slicing {len(selected_sinks)} {args.sink_functions} sinks...", file=sys.stderr, flush=True)
    sliced_at = time.monotonic()
    for index, sink in enumerate(selected_sinks, 1):
        full = slices.slice_of(program, sink, max(BUDGETS))
        for budget in BUDGETS:
            cut = slices.cut(program, full, budget)
            rendered = slices.render(program, cut)
            digest = hashlib.sha256(rendered.encode()).hexdigest()
            per_budget[budget]["packets"].setdefault(digest, slices.tokens(rendered))
            lines = covered_lines(cut)
            functions = {span.function for span in cut.spans if span.function}
            for bug in labels:
                changed_hit = bool(lines & changed_sets[bug])
                context_hit = bool(functions & label_sets[bug])
                sink_hit = sink.function in label_sets[bug]
                if not (changed_hit or context_hit or sink_hit):
                    continue
                row = per_bug[bug][str(budget)]
                row["changed_line_slices"] += changed_hit
                row["label_context_slices"] += context_hit
                row["sink_in_label_function_slices"] += sink_hit
                row["changed_line_and_label_sink_slices"] += changed_hit and sink_hit
                if changed_hit:
                    row["sink_ids"].append(sink.id)
        if index % 100 == 0:
            print(f"  {index}/{len(selected_sinks)}", file=sys.stderr, flush=True)
    slice_seconds = time.monotonic() - sliced_at

    budget_summary = {}
    for budget, values in per_budget.items():
        packet_tokens = values["packets"]
        budget_summary[str(budget)] = {
            "unique_packets": len(packet_tokens),
            "total_tokens": sum(packet_tokens.values()),
            "median_tokens": sorted(packet_tokens.values())[len(packet_tokens) // 2]
            if packet_tokens else 0,
            "bugs_with_changed_line": sum(per_bug[bug][str(budget)]["changed_line_slices"] > 0
                                          for bug in per_bug),
            "bugs_with_label_context": sum(per_bug[bug][str(budget)]["label_context_slices"] > 0
                                           for bug in per_bug),
            "bugs_with_sink_in_label_function": sum(
                per_bug[bug][str(budget)]["sink_in_label_function_slices"] > 0 for bug in per_bug),
        }

    result = {
        "schema": 1,
        "target": target,
        "interpretation": "structural gate only; not an end-to-end discovery result",
        "sink_function_selection": args.sink_functions,
        "budgets": list(BUDGETS),
        "scope_functions": len(scope_ids),
        "scan_functions": len(scan.functions),
        "scan_parses": scan.parses,
        "scan_failed_parses": scan.failed_parses,
        "scan_error_diagnostics": scan.error_diagnostics,
        "all_sinks": len(all_sinks),
        "selected_sinks": len(selected_sinks),
        "bounded_summary_functions": len(program.bounded),
        "timing_seconds": {
            "scan": round(scan_seconds, 3),
            "program": round(program_seconds, 3),
            "slices": round(slice_seconds, 3),
            "total": round(time.monotonic() - started, 3),
        },
        "budget_summary": budget_summary,
        "bugs": per_bug,
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        print(f"wrote {args.output}", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()

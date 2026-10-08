#!/usr/bin/env python3
"""Build the stage-2 P/R/C boundary inventory without calling Jev."""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from sift import cfamily
from sift.candidates import candidates, callsites
from sift.code import Call

RULE = "source-callsite-boundaries-v1"
REQUIRED_CALL_FIELDS = {
    "caller", "line", "kind", "callee", "callee_name", "passes_values",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True,
                        help="completed stage-1 run directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=Path,
                        help="rescan this target when the stage-1 calls lack source spans")
    parser.add_argument("--compile-db", type=Path, action="append",
                        help="compile_commands.json for --target; repeat to add configurations")
    parser.add_argument("--relocate-compile-db-from", type=Path,
                        help="replace this old absolute root in a moved compile database")
    parser.add_argument("--environment",
                        help="container image or other execution-environment identifier")
    args = parser.parse_args()
    if bool(args.target) != bool(args.compile_db):
        parser.error("--target and --compile-db must be used together")
    if args.relocate_compile_db_from and not args.target:
        parser.error("--relocate-compile-db-from requires --target")
    args.output.mkdir(parents=True, exist_ok=True)

    manifest = _object(args.run / "manifest.json")
    revision = manifest.get("revision")
    if revision is not None and not isinstance(revision, str):
        raise ValueError("manifest revision must be a string or null")

    extraction = {}
    if args.target:
        extraction_started = time.monotonic()
        scan_dbs = args.compile_db
        if args.relocate_compile_db_from:
            scan_dbs = [
                _relocate_compile_db(path, args.relocate_compile_db_from,
                                     args.target, args.output, number)
                for number, path in enumerate(args.compile_db)
            ]
        scan = cfamily.scan(args.target, scan_dbs)
        calls = scan.calls
        extraction = {
            "target": str(args.target.resolve()),
            "compile_databases": [{
                "path": str(path.resolve()),
                "sha256": _sha(path),
                "scan_path": str(scan_path.resolve()),
                "scan_sha256": _sha(scan_path),
            } for path, scan_path in zip(args.compile_db, scan_dbs, strict=True)],
            "relocated_from": (str(args.relocate_compile_db_from)
                               if args.relocate_compile_db_from else None),
            "parses": scan.parses,
            "failed_parses": scan.failed_parses,
            "error_diagnostics": scan.error_diagnostics,
            "functions": len(scan.functions),
            "unanalyzed": dict(sorted(Counter(
                item.reason for item in scan.unanalyzed
            ).items())),
            "seconds": round(time.monotonic() - extraction_started, 3),
            "environment": args.environment,
        }
    else:
        call_rows = _rows(args.run / "calls.jsonl")
        calls = []
        for number, row in enumerate(call_rows, 1):
            missing = REQUIRED_CALL_FIELDS - row.keys()
            if missing:
                raise ValueError(f"calls.jsonl:{number}: missing {sorted(missing)}")
            try:
                calls.append(Call(**row))
            except TypeError as error:
                raise ValueError(f"calls.jsonl:{number}: {error}") from error

    selected_rows = _rows(args.run / "selected.jsonl")
    selected = set()
    for number, row in enumerate(selected_rows, 1):
        function_id = row.get("function_id")
        if not isinstance(function_id, str):
            raise ValueError(f"selected.jsonl:{number}: invalid function_id")
        selected.add(function_id)

    scoped = [call for call in calls if call.caller in selected]
    boundary_started = time.monotonic()
    atoms = callsites(scoped, revision)
    by_policy = {policy: candidates(atoms, policy) for policy in ("P", "R", "C")}

    output_manifest = {
        "rule": RULE,
        "revision": revision,
        "stage1_manifest_sha256": _sha(args.run / "manifest.json"),
        "calls_sha256": None if args.target else _sha(args.run / "calls.jsonl"),
        "selected_sha256": _sha(args.run / "selected.jsonl"),
        "extraction": extraction,
        "selected_callers": len(selected),
        "calls": len(scoped),
        "call_kinds": dict(sorted(Counter(call.kind for call in scoped).items())),
        "callsites": len(atoms),
        "callsites_without_source": sum(not atom.path or not atom.code for atom in atoms),
        "callsites_without_control_region": sum(not atom.control_regions for atom in atoms),
        "candidates": {policy: len(rows) for policy, rows in by_policy.items()},
        "boundary_seconds": round(time.monotonic() - boundary_started, 3),
    }
    _json(args.output / "manifest.json", output_manifest)
    _jsonl(args.output / "callsites.jsonl", [asdict(atom) for atom in atoms])
    for policy, rows in by_policy.items():
        _jsonl(args.output / f"candidates-{policy.lower()}.jsonl", [{
            "id": candidate.id,
            "policy": candidate.policy,
            "caller": candidate.caller,
            "callees": candidate.callees,
            "callsite_ids": [atom.id for atom in candidate.callsites],
        } for candidate in rows])
    print(json.dumps(output_manifest, ensure_ascii=False))


def _object(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected one JSON object")
    return value


def _rows(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected one JSON object")
        rows.append(value)
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relocate_compile_db(path: Path, old_root: Path, target: Path,
                         output: Path, number: int) -> Path:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: expected a JSON array of compile commands")
    old = str(old_root)
    new = str(target.resolve())

    def moved(value):
        if isinstance(value, str):
            return value.replace(old, new)
        if isinstance(value, list):
            return [moved(item) for item in value]
        return value

    relocated = [{key: moved(value) for key, value in row.items()} for row in rows]
    destination = output / f"compile_commands.relocated-{number}.json"
    _json(destination, relocated)
    return destination


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


if __name__ == "__main__":
    main()

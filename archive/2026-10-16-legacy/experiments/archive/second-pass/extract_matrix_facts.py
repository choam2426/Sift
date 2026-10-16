#!/usr/bin/env python3
"""Export neutral CodeQL facts from a pinned C/C++ database for matrix inputs.

The output is a frozen, ignored run directory. No security query or model is run.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
QUERIES = {
    "functions": "source_functions.ql",
    "calls": "source_call_edges.ql",
    "call_arguments": "db_call_arguments.ql",
    "parameters": "db_parameters.ql",
    "parameter_accesses": "matrix_parameter_accesses.ql",
    "field_accesses": "db_field_accesses.ql",
    "conditions": "db_conditions.ql",
    "type_declarations": "source_type_declarations.ql",
    "unresolved_calls": "unresolved_source_calls.ql",
    "local_value_steps": "matrix_local_value_steps.ql",
    "guarded_effects": "matrix_guarded_effects.ql",
    "observable_effects": "matrix_observable_effects.ql",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    if args.output.exists():
        raise ValueError("output already exists; choose a new run ID")
    source_root = args.source_root.resolve()
    database = args.database.resolve()
    codeql = args.codeql.resolve()
    if not codeql.is_file() or not (database / "codeql-database.yml").is_file():
        raise ValueError("missing CodeQL CLI or database")
    revision = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.run(["git", "-C", str(source_root), "diff", "--quiet", "HEAD", "--"],
                      check=False).returncode:
        raise ValueError("source snapshot has tracked changes")
    database_config = (database / "codeql-database.yml").read_text()
    db_revision = re.search(r"(?m)^  sha: ([0-9a-f]{40})$", database_config)
    db_source = re.search(r"(?m)^sourceLocationPrefix: (.+)$", database_config)
    if (not db_revision or db_revision.group(1) != revision or not db_source or
            Path(db_source.group(1)).resolve() != source_root):
        raise ValueError("CodeQL database revision or source root mismatch")
    cli_version = subprocess.check_output([str(codeql), "version"], text=True).splitlines()[0]
    base_ql_dir = HERE / "codeql-pilot/cpp"
    args.output.mkdir(parents=True)
    ql_dir = base_ql_dir
    if args.scope_regex != "C/.*":
        ql_dir = args.output / "queries"
        ql_dir.mkdir()
        (ql_dir / "qlpack.yml").write_bytes((base_ql_dir / "qlpack.yml").read_bytes())
        (ql_dir / "codeql-pack.lock.yml").write_bytes(
            (base_ql_dir / "codeql-pack.lock.yml").read_bytes())
        for query_name in QUERIES.values():
            source = (base_ql_dir / query_name).read_text()
            source = source.replace('regexpMatch("C/.*")',
                                    f"regexpMatch({json.dumps(args.scope_regex)})")
            (ql_dir / query_name).write_text(source)
    files = {}
    try:
        for name, query_name in QUERIES.items():
            query = ql_dir / query_name
            bqrs = args.output / f"{name}.bqrs"
            csv_path = args.output / f"{name}.csv"
            subprocess.run([str(codeql), "query", "run", str(query),
                            "--database", str(database), "--output", str(bqrs)], check=True)
            subprocess.run([str(codeql), "bqrs", "decode", str(bqrs),
                            "--format=csv", "--output", str(csv_path)], check=True)
            with csv_path.open(newline="") as stream:
                row_count = sum(1 for _ in csv.DictReader(stream))
            files[name] = {"query": query_name, "query_sha256": digest(query),
                           "csv_sha256": digest(csv_path), "rows": row_count}
        manifest = {"status": "neutral_facts_no_model_calls", "language": "cpp",
                    "source_revision": revision, "source_root": str(source_root),
                    "source_scope_regex": args.scope_regex,
                    "codeql_cli": cli_version, "database": str(database),
                    "database_config_sha256": digest(database / "codeql-database.yml"),
                    "query_pack_sha256": digest(ql_dir / "qlpack.yml"), "files": files}
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        (args.output / "INCOMPLETE").write_text("Fact export failed; do not use this directory.\n")
        raise
    print(json.dumps({"status": manifest["status"],
                      "rows": {name: info["rows"] for name, info in files.items()}},
                     ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--codeql", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--scope-regex", default="C/.*",
                        help="CodeQL source path pattern for the compiled C/C++ target")
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())

#!/usr/bin/env python3
"""Extract a patched C snapshot in the same file/function scope as a baseline."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess


def clang_definitions(path, source_root, track):
    run = subprocess.run(
        ["clang", "-Xclang", "-ast-dump=json", "-fsyntax-only", str(path)],
        capture_output=True, text=True,
    )
    if run.returncode:
        raise ValueError("Clang failed to parse " + str(path))
    tree = json.loads(run.stdout)
    lines = path.read_text(errors="replace").splitlines(keepends=True)
    relative = path.relative_to(source_root).as_posix()
    current_file = None
    result = []
    for node in tree.get("inner", []):
        location = node.get("loc", {})
        if "file" in location:
            current_file = Path(location["file"]).resolve()
        if (current_file != path.resolve() or node.get("kind") != "FunctionDecl"
                or not any(child.get("kind") == "CompoundStmt" for child in node.get("inner", []))):
            continue
        # Macro-generated definitions have no complete source body in this file.
        start = location.get("line")
        if not isinstance(start, int):
            continue
        end = node.get("range", {}).get("end", {}).get("line", start)
        if not isinstance(end, int):
            raise ValueError("function lacks an end line: " + str(path))
        name = node["name"]
        result.append({
            "id": f"{track}:{relative}:{start}:{name}",
            "track": track, "file": relative, "name": name,
            "qualified": name, "kind": "function",
            "params": node["type"]["qualType"],
            "start_line": start, "end_line": end,
            "code": "".join(lines[start - 1:end]).rstrip("\r\n"),
        })
    return result


def paired_functions(baseline_root, target_root, baseline_functions, target_track):
    baseline = [json.loads(line) for line in baseline_functions.read_text().splitlines() if line]
    by_file = defaultdict(list)
    for row in baseline:
        by_file[row["file"]].append(row)
    result = []
    changed = []
    removed = []
    added = []
    for relative, original in sorted(by_file.items()):
        before = baseline_root / relative
        after = target_root / relative
        if before.read_bytes() == after.read_bytes():
            for row in original:
                updated = dict(row, track=target_track)
                updated["id"] = f"{target_track}:{relative}:{row['start_line']}:{row['name']}"
                result.append(updated)
            continue
        changed.append(relative)
        original_parsed = clang_definitions(before, baseline_root, original[0]["track"])
        if {row["id"]: row for row in original_parsed} != {row["id"]: row for row in original}:
            raise ValueError("Clang extraction does not reproduce baseline file: " + relative)
        current = clang_definitions(after, target_root, target_track)
        original_names = sorted(row["name"] for row in original)
        current_names = sorted(row["name"] for row in current)
        removed.extend(f"{relative}:{name}" for name in sorted(set(original_names) - set(current_names)))
        added.extend(f"{relative}:{name}" for name in sorted(set(current_names) - set(original_names)))
        result.extend(current)
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("paired function inventory has duplicate IDs")
    if len(result) != len(baseline) - len(removed) + len(added):
        raise ValueError("paired function inventory changed in an ambiguous way")
    return result, changed, removed, added, len(by_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--baseline-functions", type=Path, required=True)
    parser.add_argument("--target-track", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows, changed, removed, added, file_count = paired_functions(
        args.baseline_root, args.target_root, args.baseline_functions, args.target_track
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    print("files", file_count, "functions", len(rows), "changed files", changed,
          "removed", removed, "added", added, "output", args.output)


if __name__ == "__main__":
    main()

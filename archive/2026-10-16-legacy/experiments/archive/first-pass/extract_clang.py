#!/usr/bin/env python3
"""Extract definitions in a Clang-compiled C/C++ library configuration."""

import argparse
from bisect import bisect_right
import fnmatch
import json
from pathlib import Path
import subprocess


KINDS = {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl",
         "CXXDestructorDecl", "CXXConversionDecl"}


def point(location):
    return location.get("expansionLoc", location)


def line_of(source, offset):
    if not isinstance(offset, int) or not 0 <= offset < len(source):
        return None
    return bisect_right([0] + [i + 1 for i, byte in enumerate(source) if byte == 10], offset)


def definitions(tree, source_root, patterns, track):
    sources = {}
    rows = {}
    skipped = []

    def normalized_file(raw):
        if not raw:
            return None
        resolved = (source_root / raw).resolve()
        try:
            relative = resolved.relative_to(source_root.resolve()).as_posix()
        except ValueError:
            return None
        return relative if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns) else None

    def visit(parent, inherited):
        current = inherited
        for node in parent.get("inner", []):
            location = node.get("loc", {})
            explicit_file = (location.get("file")
                             or location.get("expansionLoc", {}).get("file")
                             or location.get("spellingLoc", {}).get("file"))
            if explicit_file:
                current = explicit_file
            raw_file = explicit_file or current
            relative = normalized_file(raw_file)
            if (relative and node.get("kind") in KINDS and not node.get("isImplicit")
                    and any(child.get("kind") == "CompoundStmt" for child in node.get("inner", []))):
                source = sources.setdefault(relative, (source_root / relative).read_bytes())
                span = node.get("range", {})
                start_offset = point(span.get("begin", {})).get("offset")
                end_offset = point(span.get("end", {})).get("offset")
                start = line_of(source, start_offset)
                end = line_of(source, end_offset)
                if start is None or end is None or end < start:
                    skipped.append((relative, node.get("name"), start_offset, end_offset))
                else:
                    lines = source.decode("utf-8").splitlines(keepends=True)
                    code = "".join(lines[start - 1:end]).rstrip("\r\n")
                    if "{" not in code or "}" not in code:
                        skipped.append((relative, node.get("name"),
                                        "macro-generated body unavailable"))
                        visit(node, raw_file)
                        continue
                    key = (relative, start, end)
                    name = node.get("name", "<anonymous>")
                    row = {
                        "id": f"{track}:{relative}:{start}:{name}",
                        "track": track, "file": relative, "name": name,
                        "qualified": name, "kind": node["kind"], "params": "",
                        "start_line": start, "end_line": end, "code": code,
                    }
                    # Template instantiations repeat one source definition.
                    if key not in rows or len(name) < len(rows[key]["name"]):
                        rows[key] = row
            visit(node, raw_file)

    visit(tree, None)
    return rows, skipped


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--source-root", type=Path, required=True)
    cli.add_argument("--translation-unit", action="append", required=True)
    cli.add_argument("--include", action="append", required=True)
    cli.add_argument("--language", choices=("c", "cpp"), required=True)
    cli.add_argument("--track", required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--flag", action="append", default=[])
    args = cli.parse_args()
    compiler = "clang++" if args.language == "cpp" else "clang"
    all_rows = {}
    skipped = []
    for unit in args.translation_unit:
        command = [compiler, *args.flag, "-Xclang", "-ast-dump=json",
                   "-fsyntax-only", unit]
        result = subprocess.run(command, cwd=args.source_root, capture_output=True,
                                text=True)
        if result.returncode:
            raise ValueError(f"Clang failed on {unit}: {result.stderr[:1000]}")
        found, omitted = definitions(json.loads(result.stdout), args.source_root,
                                     args.include, args.track)
        all_rows.update(found)
        skipped.extend(omitted)
    rows = sorted(all_rows.values(), key=lambda row: (row["file"], row["start_line"], row["name"]))
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("empty or duplicate function inventory")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                   for row in rows))
    print(f"functions {len(rows)} files {len({row['file'] for row in rows})}")
    print(f"excluded definitions without a complete source body {len(skipped)}: {skipped[:10]}")
    print(f"largest code bytes {max(len(row['code'].encode()) for row in rows)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extract complete Python function bodies from a pinned source tree."""

import argparse
import ast
import json
from pathlib import Path


def functions(source_root, source_subdir, track):
    result = []
    for path in sorted((source_root / source_subdir).rglob("*.py")):
        relative = path.relative_to(source_root).as_posix()
        lines = path.read_text().splitlines(keepends=True)
        tree = ast.parse("".join(lines), filename=relative)

        def visit(node, parents):
            next_parents = parents
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = ".".join((*parents, node.name))
                next_parents = (*parents, node.name)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([node.lineno, *(item.lineno for item in node.decorator_list)])
                    code = "".join(lines[start - 1:node.end_lineno]).rstrip("\r\n")
                    result.append({
                        "id": f"{track}:{relative}:{start}:{qualified}",
                        "track": track, "file": relative, "name": node.name,
                        "qualified": qualified,
                        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        "params": "", "start_line": start, "end_line": node.end_lineno,
                        "code": code,
                    })
            for child in ast.iter_child_nodes(node):
                visit(child, next_parents)

        visit(tree, ())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-subdir", type=Path, required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = functions(args.source_root, args.source_subdir, args.track)
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate function IDs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    print("files", len(list((args.source_root / args.source_subdir).rglob("*.py"))),
          "functions", len(rows), "output", args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extract source-exact functions from a pinned C, C++, Rust, or Go tree.

The inventory is syntactic: conditional compilation branches remain included.
Rust cfg(test) modules and Go _test.go files are excluded from the source scope.
"""

import argparse
import fnmatch
import json
from pathlib import Path
import subprocess

from tree_sitter import Language, Parser


GRAMMAR = {
    "c": ("tree_sitter_c", (".c", ".h"), {"function_definition"}),
    "cpp": ("tree_sitter_cpp", (".cpp", ".h", ".hpp"), {"function_definition"}),
    "rust": ("tree_sitter_rust", (".rs",), {"function_item"}),
    "go": ("tree_sitter_go", (".go",), {"function_declaration", "method_declaration"}),
}


def source_files(root, language, includes):
    tracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"], text=True
    ).split("\0")
    extensions = GRAMMAR[language][1]
    files = []
    for name in tracked:
        if not name or not name.endswith(extensions):
            continue
        if not any(fnmatch.fnmatch(name, pattern) for pattern in includes):
            continue
        if language == "go" and (name.endswith("_test.go") or "/test/" in f"/{name}/"):
            continue
        files.append(name)
    return sorted(files)


def rust_test_ranges(root, source):
    """Find cfg(test) modules, including nested ones, from sibling attributes."""
    ranges = []

    def visit(node):
        previous = None
        for child in node.children:
            if child.type == "mod_item" and previous is not None:
                attribute = source[previous.start_byte:previous.end_byte].decode(errors="replace")
                if previous.type == "attribute_item" and "cfg(test)" in attribute.replace(" ", ""):
                    ranges.append((child.start_byte, child.end_byte))
            visit(child)
            if child.is_named:
                previous = child

    visit(root)
    return ranges


def declarator_name(node, source):
    if node.type in ("identifier", "field_identifier", "type_identifier", "qualified_identifier", "operator_name", "destructor_name"):
        return source[node.start_byte:node.end_byte].decode(errors="replace")
    name = node.child_by_field_name("name")
    if name is not None:
        return source[name.start_byte:name.end_byte].decode(errors="replace")
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        found = declarator_name(declarator, source)
        if found != "<anonymous>":
            return found
    for child in node.named_children:
        if child.type in ("identifier", "field_identifier", "type_identifier", "qualified_identifier", "operator_name"):
            return source[child.start_byte:child.end_byte].decode(errors="replace")
        found = declarator_name(child, source)
        if found:
            return found
    return "<anonymous>"


def extract_file(path, relative, language, parser, track):
    source = path.read_bytes()
    tree = parser.parse(source)
    root = tree.root_node
    if root.end_byte != len(source):
        raise ValueError(f"parser could not read the whole file: {relative}")
    excluded = rust_test_ranges(root, source) if language == "rust" else []
    lines = source.decode("utf-8").splitlines(keepends=True)
    rows = []
    function_nodes = []
    function_types = GRAMMAR[language][2]

    def visit(node):
        if any(start <= node.start_byte < end for start, end in excluded):
            return
        if node.type in function_types:
            function_nodes.append(node)
            start = node.start_point.row + 1
            end = node.end_point.row + (1 if node.end_point.column else 0)
            name = declarator_name(node, source)
            code = "".join(lines[start - 1:end]).rstrip("\r\n")
            if not code.strip():
                raise ValueError(f"empty function at {relative}:{start}")
            rows.append({
                "id": f"{track}:{relative}:{start}:{name}",
                "track": track,
                "file": relative,
                "name": name,
                "qualified": name,
                "kind": node.type,
                "params": "",
                "start_line": start,
                "end_line": end,
                "code": code,
            })
        for child in node.named_children:
            visit(child)

    visit(root)
    return rows, len(excluded), root.has_error, sum(
        node.has_error for node in function_nodes
    )


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--source-root", required=True, type=Path)
    cli.add_argument("--language", choices=GRAMMAR, required=True)
    cli.add_argument("--include", action="append", required=True,
                     help="tracked file glob, repeatable")
    cli.add_argument("--track", required=True)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    module = __import__(GRAMMAR[args.language][0])
    parser = Parser(Language(module.language()))
    files = source_files(args.source_root, args.language, args.include)
    if not files:
        cli.error("no source files matched")
    rows = []
    excluded_modules = 0
    parse_error_files = []
    functions_with_parse_errors = 0
    for relative in files:
        found, excluded, has_error, function_errors = extract_file(
            args.source_root / relative, relative, args.language, parser, args.track
        )
        rows.extend(found)
        excluded_modules += excluded
        functions_with_parse_errors += function_errors
        if has_error:
            parse_error_files.append(relative)
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("empty function inventory or duplicate IDs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                   for row in rows))
    print(f"files {len(files)} functions {len(rows)} cfg(test) modules excluded {excluded_modules}")
    print(f"parser error files {parse_error_files} functions containing parser errors {functions_with_parse_errors}")
    print(f"largest code bytes {max(len(row['code'].encode()) for row in rows)}")


if __name__ == "__main__":
    main()

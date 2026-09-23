#!/usr/bin/env python3
"""Extract function units from a target checkout -> JSONL. Needs .venv (tree-sitter).

Usage: .venv/bin/python scripts/extract.py --track discourse \
         --root targets/discourse --scope app lib --out data/discourse.functions.jsonl
"""
import argparse
import hashlib
import json
import os
import sys

from tree_sitter import Language, Parser
import tree_sitter_ruby as tsruby

CLASSISH = ("class", "module", "singleton_class")
METHODISH = ("method", "singleton_method")


def walk(node, stack, out, src, rel, track):
    if node.type in CLASSISH:
        name = None
        for ch in node.children:
            if ch.type in ("constant", "scope_resolution", "identifier", "self",
                           "call", "assignment"):
                name = src[ch.start_byte:ch.end_byte].decode("utf8", "replace")
                break
        stack = stack + [name or "?"]
    if node.type in METHODISH:
        mname, params = "?", ""
        for ch in node.children:
            if ch.type in ("identifier", "constant", "operator",
                           "setter", "symbol"):
                mname = src[ch.start_byte:ch.end_byte].decode("utf8", "replace")
            if ch.type == "method_parameters":
                params = src[ch.start_byte:ch.end_byte].decode("utf8", "replace")
        kind = "singleton" if node.type == "singleton_method" else "instance"
        sep = "." if kind == "singleton" else "#"
        qual = (".".join(stack) + sep + mname) if stack else mname
        code = src[node.start_byte:node.end_byte].decode("utf8", "replace")
        uid = f"{track}:{rel}:{node.start_point[0] + 1}:{mname}"
        out.append({"id": uid, "track": track, "file": rel, "name": mname,
                    "qualified": qual, "kind": kind, "params": params,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1, "code": code})
        return  # do not descend into nested defs separately
    for ch in node.children:
        walk(ch, stack, out, src, rel, track)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--scope", nargs="+", default=["app", "lib"])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    parser = Parser(Language(tsruby.language()))
    files, funcs, errors = 0, [], []
    for scope in a.scope:
        base = os.path.join(a.root, scope)
        for dirpath, _, names in os.walk(base):
            for fn in sorted(names):
                if not fn.endswith(".rb"):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, a.root)
                try:
                    with open(p, "rb") as f:
                        src = f.read()
                except OSError as e:
                    errors.append(f"{rel}: {e}")
                    continue
                files += 1
                tree = parser.parse(src)
                if tree.root_node.has_error:
                    errors.append(f"{rel}: parse-error-nodes")
                walk(tree.root_node, [], funcs, src, rel, a.track)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        for fn in funcs:
            f.write(json.dumps(fn, ensure_ascii=False) + "\n")
    digest = hashlib.sha256(open(a.out, "rb").read()).hexdigest()[:16]
    print(f"files={files} functions={len(funcs)} errors={len(errors)} "
          f"sha={digest}")
    for e in errors[:10]:
        print("  ERR", e, file=sys.stderr)


if __name__ == "__main__":
    main()

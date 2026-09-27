"""Source code lookup. v0.1.0 reads C/C++ source with tree-sitter (ADR 0014)."""

import re
from dataclasses import dataclass
from pathlib import Path

import tree_sitter as ts
import tree_sitter_c
import tree_sitter_cpp

C = ts.Language(tree_sitter_c.language())
CPP = ts.Language(tree_sitter_cpp.language())
LANGUAGES = {".c": C, ".h": C, ".cc": CPP, ".cpp": CPP, ".cxx": CPP, ".hh": CPP, ".hpp": CPP}
NAME_NODES = {"identifier", "field_identifier", "qualified_identifier",
              "destructor_name", "operator_name"}
# Attribute macros alone on a line (`static\nZ7_NO_INLINE\nSRes f(...)`) stop tree-sitter
# from seeing a definition, so they are blanked before parsing.
MASKED_LINE = re.compile(rb"^[ \t]*[A-Z][A-Z0-9_]*[ \t]*$", re.MULTILINE)
KEYWORDS = {"if", "do", "while", "for", "switch", "return", "sizeof", "else"}


@dataclass(frozen=True)
class Function:
    id: str          # "<path>:<start_line>:<name>", stable across runs of one snapshot
    name: str
    path: str        # relative to the target root
    start_line: int  # 1-based, inclusive
    end_line: int
    code: str        # full source text of the definition
    parse_error: bool


def functions(root: Path) -> list[Function]:
    """Every function definition under root, in path and line order."""
    found = []
    for path in sorted(p for p in root.rglob("*") if p.suffix in LANGUAGES and p.is_file()):
        found += functions_in(path.read_bytes(), path.relative_to(root).as_posix(),
                              LANGUAGES[path.suffix])
    return found


def functions_in(source: bytes, path: str, language: ts.Language) -> list[Function]:
    tree = ts.Parser(language).parse(_masked(source))  # same byte offsets as source
    found = []
    covered_to = -1  # a definition inside another one's body is a misparse, not a function
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "function_definition" and node.start_byte > covered_to and (name := _name(node)):
            end = _body_end(source, node)
            covered_to = end
            line = node.start_point.row + 1
            found.append(Function(
                id=f"{path}:{line}:{name}", name=name, path=path,
                start_line=line, end_line=source.count(b"\n", 0, end) + 1,
                code=source[node.start_byte:end].decode(errors="replace"),
                parse_error=node.has_error))
        stack.extend(reversed(node.children))
    return found


def _body_end(source: bytes, definition: ts.Node) -> int:
    """End of the body by matching braces in the text.

    tree-sitter does not know macros, so a statement macro without a semicolon
    (e.g. `PRF_STR("x")`) can make it end a body thousands of lines late.
    Comments, literals and #else/#elif branches are skipped.
    """
    body = definition.child_by_field_name("body")
    if body is None or source[body.start_byte:body.start_byte + 1] != b"{":
        return definition.end_byte
    depth, skipping, i, n = 0, [], body.start_byte, len(source)
    line_start = True
    while i < n:
        c = source[i:i + 1]
        if line_start and c == b"#":
            directive = source[i + 1:_line_end(source, i)].split()
            word = directive[0].decode(errors="replace") if directive else ""
            if word.startswith("if"):
                skipping.append(False)
            elif word in ("else", "elif"):
                if skipping:
                    skipping[-1] = True
                else:
                    skipping.append(True)  # the #if opened before this function
            elif word == "endif" and skipping:
                skipping.pop()
            while i < n and not (source[i:i + 1] == b"\n" and source[i - 1:i] != b"\\"):
                i += 1
            continue
        if c == b"\n":
            line_start = True
            i += 1
            continue
        if not c.isspace():
            line_start = False
        if source.startswith(b"//", i):
            i = _line_end(source, i)
            continue
        if source.startswith(b"/*", i):
            i = source.find(b"*/", i + 2)
            i = n if i < 0 else i + 2
            continue
        if c in (b'"', b"'"):
            i += 1
            while i < n and source[i:i + 1] not in (c, b"\n"):
                i += 2 if source[i:i + 1] == b"\\" else 1
            i += 1
            continue
        if not any(skipping):
            if c == b"{":
                depth += 1
            elif c == b"}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return definition.end_byte


def _masked(source: bytes) -> bytes:
    return MASKED_LINE.sub(lambda m: re.sub(rb"[^\n]", b" ", m.group()), source)


def _line_end(source: bytes, i: int) -> int:
    end = source.find(b"\n", i)
    return len(source) if end < 0 else end


def _name(definition: ts.Node) -> str | None:
    node = definition.child_by_field_name("declarator")
    while node is not None and node.type not in NAME_NODES:
        inner = node.child_by_field_name("declarator")
        if node.type == "function_declarator" and inner is not None and inner.type == "function_declarator":
            return inner.text.decode()  # name made by a macro, e.g. PREFIX(scanComment)
        node = inner
    if node is None or node.text.decode() in KEYWORDS:  # a statement misread around a macro
        return None
    return node.text.decode()

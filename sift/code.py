"""What a scan finds in source code, and a tolerant tree-sitter pass for estimates (ADR 0014).

Function boundaries come from a compiler front end (sift.cfamily for C/C++). tree-sitter
does not know the preprocessor, so here it only proposes where definitions probably are:
code the compiler never saw is reported from these estimates, never evaluated from them.
"""

from dataclasses import dataclass
from pathlib import Path

import tree_sitter as ts
import tree_sitter_c
import tree_sitter_cpp

C = ts.Language(tree_sitter_c.language())
CPP = ts.Language(tree_sitter_cpp.language())
LANGUAGES = {".c": C, ".h": C, ".inc": C, ".cc": CPP, ".cpp": CPP, ".cxx": CPP,
             ".hh": CPP, ".hpp": CPP, ".hxx": CPP}
NAME_NODES = {"identifier", "field_identifier", "qualified_identifier",
              "destructor_name", "operator_name"}
KEYWORDS = {"if", "do", "while", "for", "switch", "return", "sizeof", "else"}


@dataclass(frozen=True)
class Function:
    id: str          # "<path>:<start_line>:<name>", stable across runs of one snapshot
    name: str        # names joined by ", " when one source span defines several (e.g. #include-d twice)
    path: str        # relative to the target root
    start_line: int  # 1-based, inclusive
    end_line: int
    code: str        # exact source text of the definition
    configs: tuple[str, ...] = ()  # configurations in which the compiler saw it


@dataclass(frozen=True)
class Unanalyzed:
    path: str
    start_line: int
    end_line: int
    name: str | None  # tree-sitter's guess of the definition there
    reason: str


@dataclass
class Scan:
    functions: list[Function]
    unanalyzed: list[Unanalyzed]
    configs: list[str]
    parses: int
    error_diagnostics: int
    failed_parses: int  # configurations libclang refused; the files may still parse in others


@dataclass(frozen=True)
class Definition:
    name: str
    path: str
    start_line: int
    end_line: int


def definitions(root: Path) -> list[Definition]:
    """Where tree-sitter believes definitions are. Spans can be wrong around macros."""
    found = []
    for path in sorted(p for p in root.rglob("*") if p.suffix in LANGUAGES and p.is_file() and not p.is_symlink()):
        found += definitions_in(path.read_bytes(), path.relative_to(root).as_posix(),
                                LANGUAGES[path.suffix])
    return found


def definitions_in(source: bytes, path: str, language: ts.Language) -> list[Definition]:
    stack, found = [ts.Parser(language).parse(source).root_node], []
    while stack:
        node = stack.pop()
        if node.type == "function_definition" and (name := _name(node)):
            found.append(Definition(name, path, node.start_point.row + 1, node.end_point.row + 1))
        stack.extend(reversed(node.children))
    return found


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

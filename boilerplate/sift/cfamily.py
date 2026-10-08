"""C/C++ functions from libclang over every configuration we can reach (ADR 0014).

One configuration is what one compile command sees; everything under a false #if is
skipped. To see as much as possible, each file is parsed with its compile command, with
other targets, and then with the macros of still-skipped definitions defined and
undefined. Whatever no configuration reached is reported as unanalyzed.
"""

import ctypes
import json
import os
import re
import shlex
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from pathlib import Path

import clang.cindex as ci

from sift.code import Call, Function, Scan, Unanalyzed, definitions

SOURCES = {".c", ".cc", ".cpp", ".cxx"}
TARGETS = ("x86_64-linux-gnu", "aarch64-linux-gnu", "i686-linux-gnu", "x86_64-pc-windows-msvc")
FLIP_ROUNDS = 2
PARSE_OPTIONS = 0x01 | 0x200  # DetailedPreprocessingRecord (skipped ranges) | KeepGoing
KINDS = {ci.CursorKind.FUNCTION_DECL, ci.CursorKind.CXX_METHOD, ci.CursorKind.CONSTRUCTOR,
         ci.CursorKind.DESTRUCTOR, ci.CursorKind.CONVERSION_FUNCTION, ci.CursorKind.FUNCTION_TEMPLATE}
KEPT_WITH_VALUE = {"-D", "-U", "-I", "-isystem", "-include", "-target", "--target", "-std", "-x"}
DROPPED_WITH_VALUE = {"-o", "-MF", "-MT", "-MQ", "-arch", "-Xclang", "-mllvm", "-Xpreprocessor", "-Xlinker"}
CODEGEN_ONLY = {"-fPIC", "-fpic", "-fPIE", "-fpie"}
DIRECTIVE = re.compile(r"\s*#\s*(if|ifdef|ifndef|elif|endif)\b(.*)")
IDENT = re.compile(r"\b(?!defined\b)[A-Za-z_]\w*\b")


def scan(root: Path, compile_dbs: list[Path], workers: int | None = None) -> Scan:
    root = root.resolve()
    commands = _commands(root, compile_dbs)
    if not commands:
        raise ValueError("no compile command covers a source file under the target")
    covered = {path for path, _ in commands}
    outside = [(p, _borrowed(commands, p)) for p in sorted(root.rglob("*"))
               if p.suffix in SOURCES and not p.is_symlink() and p not in covered]

    state = _State(root)
    base = [(p, a, "compile database") for p, a in commands]
    base += [(p, a, "borrowed flags") for p, a in outside]
    tasks = base + [(p, _retarget(a, t), f"target {t}") for p, a, _ in base for t in TARGETS]
    with ProcessPoolExecutor(workers, initializer=_load_libclang) as pool:
        def parse_all(tasks):
            state.merge(pool.map(_parse, [(str(root), str(p), a + _system_includes(p.suffix != ".c"), label)
                                          for p, a, label in tasks]))
        parse_all(tasks)
        estimates = definitions(root)
        for _ in range(FLIP_ROUNDS):
            if not (flips := state.flips(estimates, base)):
                break
            parse_all(flips)
    return state.result(estimates)


class _State:
    def __init__(self, root: Path):
        self.root = root
        self.functions = {}               # (path, end) -> [names, configs, start, first line, last line]
        self.active = defaultdict(set)    # path -> lines some configuration compiled
        self.seen = set()                 # paths some translation unit entered
        self.tried = set()                # (source, label) macro flips already parsed
        self.usr = defaultdict(set)       # clang USR -> (path, end) of its definitions, one per configuration
        # One source call may resolve differently across configurations. Keep those
        # interpretations separate here; sift.candidates joins them into one source atom.
        self.calls = {}                   # (caller path, end, call path, offset, callee USR) -> call facts
        self.configs, self.parses, self.errors, self.failed = [], 0, 0, 0

    def merge(self, results):
        for result in results:
            self.parses += 1
            self.errors += result["errors"]
            self.failed += result["failed"]
            if result["label"] not in self.configs:
                self.configs.append(result["label"])
            for path, skipped in result["files"].items():
                self.seen.add(path)
                self.active[path] |= set(range(1, _line_count(self.root / path) + 1)) - set(skipped)
            for path, start, end, (first, last), name, usr in result["functions"]:
                # attribute macros can move the start between configurations; the closing brace stays
                self.usr[usr].add((path, end))
                entry = self.functions.setdefault((path, end), [set(), set(), start, first, last])
                entry[0].add(name)
                entry[1].add(result["label"])
                if start < entry[2]:
                    entry[2:4] = [start, first]
            for (path, end, offset, call_path, line, start_column, call_end_line,
                 end_column, code, region, usr, name, passes) in result["calls"]:
                key = (path, end, call_path, offset, usr)
                entry = self.calls.setdefault(
                    key,
                    [line, start_column, call_end_line, end_column, code, region,
                     name, False, set()],
                )
                entry[7] = entry[7] or passes
                entry[8].add(result["label"])

    def flips(self, estimates, base):
        """Configurations that define or undefine the macros guarding still-skipped definitions."""
        args_of = {}
        for path, args, _ in base:
            if path.is_relative_to(self.root):
                args_of.setdefault(path.relative_to(self.root).as_posix(), (path, args))
        tasks = {}
        for d in estimates:
            if d.path in args_of and d.start_line not in self.active[d.path]:
                path, args = args_of[d.path]
                names = sorted(_guards(path, d.start_line))
                flags = [[f"-D{n}=1"] for n in names] + [[f"-U{n}"] for n in names]
                if len(names) > 1:  # nested #ifdefs need their macros defined together
                    flags.append([f"-D{n}=1" for n in names])
                for extra in flags:
                    label = " ".join(extra)
                    if (path, label) not in self.tried:
                        tasks[(path, label)] = (path, args + tuple(extra), label)
        self.tried |= tasks.keys()
        return sorted(tasks.values())

    def result(self, estimates) -> Scan:
        functions, unanalyzed, ids = [], [], {}
        evaluated = defaultdict(set)  # lines inside a function's text, which Jev sees whole
        for (path, end), (names, configs, start, first, last) in sorted(self.functions.items()):
            code = (self.root / path).read_bytes()[start:end].decode(errors="replace")
            name = ", ".join(sorted(names))
            if "{" not in code:  # the body comes from a macro; its text is not in this file
                unanalyzed.append(Unanalyzed(path, first, last, name, "body produced by a macro"))
                continue
            ids[(path, end)] = f"{path}:{first}:{name}"
            functions.append(Function(ids[(path, end)], name, path, first, last, code,
                                      tuple(sorted(configs))))
            evaluated[path] |= set(range(first, last + 1))
        reported = defaultdict(set)
        for d in estimates:
            lines = set(range(d.start_line, d.end_line + 1))
            if lines & evaluated[d.path]:
                continue
            if d.path not in self.seen:
                unanalyzed.append(Unanalyzed(d.path, d.start_line, d.end_line, d.name,
                                             "no configuration parsed this file"))
            elif d.start_line not in self.active[d.path]:
                unanalyzed.append(Unanalyzed(d.path, d.start_line, d.end_line, d.name,
                                             "inactive in every configuration"))
                reported[d.path] |= lines
        # tree-sitter can miss definitions around macros, so every line of code that no
        # configuration compiled is reported, whether or not it looks like a definition
        for path in sorted(self.seen):
            text = (self.root / path).read_text(errors="replace").splitlines()
            inactive = (set(range(1, _line_count(self.root / path) + 1))
                        - self.active[path] - evaluated[path] - reported[path])
            for first, last in _blocks(inactive):
                if any(line.strip() and not line.lstrip().startswith("#") for line in text[first - 1:last]):
                    unanalyzed.append(Unanalyzed(path, first, last, None, "inactive in every configuration"))
        calls = []
        for ((path, end, call_path, _, usr),
             (line, start_column, call_end_line, end_column, code, region,
              name, passes, configs)) in sorted(
                  self.calls.items(), key=lambda item: tuple(str(part) for part in item[0])
              ):
            if (path, end) not in ids:
                continue  # the caller's body comes from a macro
            targets = sorted(ids[k] for k in self.usr.get(usr, ()) if k in ids)
            kind = "indirect" if usr is None else "direct" if targets else "external"
            for callee in targets or [None]:
                calls.append(Call(
                    ids[(path, end)], line, kind, callee, name, passes,
                    call_path, start_column, call_end_line, end_column, code, region,
                    tuple(sorted(configs)),
                ))
        return Scan(functions, unanalyzed, self.configs, self.parses, self.errors, self.failed, calls)


def _commands(root: Path, compile_dbs: list[Path]) -> list[tuple[Path, tuple[str, ...]]]:
    """Compile commands for sources under the root. When there are none, as for a header-only
    library built through a harness file elsewhere, every command is used; only definitions
    under the root are recorded either way."""
    commands = []
    for db in compile_dbs:
        for entry in json.loads(db.read_text()):
            directory = Path(entry["directory"])
            path = (directory / entry["file"]).resolve()
            if path.suffix in SOURCES:
                args = entry.get("arguments") or shlex.split(entry["command"])
                commands.append((path, _clean(args, directory)))
    inside = [c for c in commands if c[0].is_relative_to(root)]
    return list(dict.fromkeys(inside or commands))


def _clean(args, directory: Path) -> tuple[str, ...]:
    """Keep what changes how the code is read (-D, -U, -I, -std, target); drop the rest."""
    kept, i = [], 1
    while i < len(args):
        a = args[i]
        if a in KEPT_WITH_VALUE:
            kept += [a, _abs(args[i + 1], directory) if a in ("-I", "-isystem", "-include") else args[i + 1]]
            i += 2
            continue
        if a in DROPPED_WITH_VALUE:
            i += 2
            continue
        if a.startswith(("-D", "-U", "-std=", "--target=", "-m", "-f")) and a not in CODEGEN_ONLY:
            kept.append(a)
        elif a.startswith(("-I", "-isystem")):
            flag = "-I" if a.startswith("-I") else "-isystem"
            kept.append(flag + _abs(a[len(flag):], directory))
        i += 1
    return tuple(kept)


def _borrowed(commands, path: Path) -> tuple[str, ...]:
    """Flags for a source file no compile command covers: the most common ones of its language."""
    same = [a for p, a in commands if (p.suffix == ".c") == (path.suffix == ".c")]
    if same:
        return Counter(same).most_common(1)[0][0]
    # only the other language has commands; its standard and language flags would be rejected
    args = Counter(a for _, a in commands).most_common(1)[0][0]
    kept, i = [], 0
    while i < len(args):
        if args[i] in ("-std", "-x"):
            i += 2
            continue
        if not args[i].startswith("-std="):
            kept.append(args[i])
        i += 1
    return tuple(kept)


@cache
def _system_includes(cxx: bool) -> tuple[str, ...]:
    """The include paths the clang driver adds on its own; libclang alone does not know them."""
    done = subprocess.run(["clang", "-x", "c++" if cxx else "c", "-E", "-v", "-"],
                          input="", capture_output=True, text=True)
    lines = done.stderr.split("#include <...> search starts here:")[-1].split("End of search list.")[0]
    flags = []
    for entry in map(str.strip, lines.strip().splitlines()):
        if entry.endswith("(framework directory)"):
            flags += ["-iframework", entry.removesuffix("(framework directory)").strip()]
        elif entry:
            flags += ["-isystem", entry]
    return tuple(flags)


def _abs(path: str, directory: Path) -> str:
    return str((directory / path).resolve())


def _retarget(args: tuple[str, ...], target: str) -> tuple[str, ...]:
    kept = [a for a in args if not a.startswith(("--target=", "-m"))]
    return tuple(kept) + (f"--target={target}",)


def _guards(path: Path, line: int) -> set[str]:
    """Macro names in every #if/#ifdef/#elif level that encloses a line."""
    names, depth = set(), 0
    for text in reversed(path.read_text(errors="replace").splitlines()[:line - 1]):
        if not (m := DIRECTIVE.match(text)):
            continue
        word, rest = m.groups()
        if word == "endif":
            depth += 1
        elif word.startswith("if"):
            if depth == 0:
                names |= set(IDENT.findall(rest))
            else:
                depth -= 1
        elif depth == 0:  # an earlier #elif of the same chain
            names |= set(IDENT.findall(rest))
    return names


def _blocks(lines: set[int]) -> list[tuple[int, int]]:
    blocks = []
    for n in sorted(lines):
        if blocks and blocks[-1][1] == n - 1:
            blocks[-1][1] = n
        else:
            blocks.append([n, n])
    return [tuple(b) for b in blocks]


@cache
def _line_count(path: Path) -> int:
    return path.read_bytes().count(b"\n") + 1


# ---- worker process -------------------------------------------------------------------

class _RangeList(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint), ("ranges", ctypes.POINTER(ci.SourceRange))]


def _load_libclang():
    if not ci.Config.loaded:
        ci.Config.set_library_file(libclang_path())
    lib = ci.conf.lib
    lib.clang_getAllSkippedRanges.restype = ctypes.POINTER(_RangeList)
    lib.clang_getAllSkippedRanges.argtypes = [ci.TranslationUnit]
    lib.clang_disposeSourceRangeList.argtypes = [ctypes.POINTER(_RangeList)]


def libclang_path() -> str:
    if path := os.environ.get("SIFT_LIBCLANG"):
        return path
    for command in (["llvm-config", "--libdir"], ["xcode-select", "-p"]):
        try:
            out = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            continue
        for candidate in (Path(out) / "libclang.so", Path(out) / "libclang.dylib",
                          Path(out) / "usr/lib/libclang.dylib",
                          Path(out) / "Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib"):
            if candidate.exists():
                return str(candidate)
    raise RuntimeError("libclang not found; set SIFT_LIBCLANG to its path")


def _parse(task):
    root, source, args, label = task
    root = Path(root)
    try:
        tu = ci.Index.create().parse(source, args=list(args), options=PARSE_OPTIONS)
    except ci.TranslationUnitLoadError:  # e.g. flags this language rejects; other configs may parse
        return {"label": label, "functions": [], "calls": [], "files": {}, "errors": 0, "failed": 1}

    def relative(file) -> str | None:
        path = Path(file.name).resolve() if file is not None else None
        return path.relative_to(root).as_posix() if path and path.is_relative_to(root) else None

    functions, calls = [], []
    stack = list(tu.cursor.get_children())
    while stack:
        cursor = stack.pop()
        if (path := relative(cursor.extent.start.file)) is None:
            continue
        if cursor.kind in KINDS and cursor.is_definition():
            extent = cursor.extent
            functions.append((path, extent.start.offset, extent.end.offset,
                              (extent.start.line, extent.end.line), _qualified(cursor), cursor.get_usr()))
            calls += [(path, extent.end.offset, *call) for call in _calls(cursor, relative)]
        elif cursor.kind.is_declaration():  # classes, templates, namespaces, friends, extern "C"
            stack.extend(cursor.get_children())

    files = {relative(ci.File.from_name(tu, source)): []}
    for inclusion in tu.get_includes():
        files.setdefault(relative(inclusion.include), [])
    ranges = ci.conf.lib.clang_getAllSkippedRanges(tu)
    for i in range(ranges.contents.count):
        r = ranges.contents.ranges[i]
        files.setdefault(relative(r.start.file), []).extend(range(r.start.line, r.end.line + 1))
    ci.conf.lib.clang_disposeSourceRangeList(ranges)
    files.pop(None, None)
    errors = sum(d.severity >= ci.Diagnostic.Error for d in tu.diagnostics)
    return {"label": label, "functions": functions, "calls": calls, "files": files, "errors": errors, "failed": 0}


def _calls(function, relative):
    """Source-backed call facts, including the innermost lexical control arm."""
    usr = function.get_usr()
    found = []

    def record(node, region):
        target = node.referenced
        direct = target is not None and target.kind in KINDS
        passes = any(ref.kind == ci.CursorKind.DECL_REF_EXPR and ref.referenced is not None
                     and ref.referenced.kind == ci.CursorKind.PARM_DECL
                     and ref.referenced.semantic_parent is not None
                     and ref.referenced.semantic_parent.get_usr() == usr
                     for arg in node.get_arguments() for ref in arg.walk_preorder())
        start, end = node.extent.start, node.extent.end
        call_path = relative(start.file) or ""
        code = _extent_source(start, end)
        found.append((
            start.offset, call_path, start.line, start.column, end.line, end.column,
            code, region, target.get_usr() if direct else None,
            _written(node.location) or (target.spelling if target is not None else ""),
            passes,
        ))

    def visit(node, region):
        if node.kind in (ci.CursorKind.CASE_STMT, ci.CursorKind.DEFAULT_STMT,
                         ci.CursorKind.CXX_CATCH_STMT):
            region = _region(node, relative) or region
        children = list(node.get_children())
        arm_regions = _arm_regions(node, children, relative)
        for index, child in enumerate(children):
            child_region = arm_regions.get(index, region)
            if child.kind == ci.CursorKind.CALL_EXPR:
                record(child, child_region)
            visit(child, child_region)

    visit(function, None)
    return found


def _arm_regions(parent, children, relative):
    """The source spans used by the experimental R grouping policy.

    These are lexical regions, not claims about semantic control dependence.
    """
    statement_indexes = [i for i, child in enumerate(children) if child.kind.is_statement()]
    if parent.kind == ci.CursorKind.IF_STMT:
        chosen = statement_indexes
    elif parent.kind in (ci.CursorKind.FOR_STMT, ci.CursorKind.CXX_FOR_RANGE_STMT,
                         ci.CursorKind.WHILE_STMT, ci.CursorKind.DO_STMT):
        chosen = statement_indexes[-1:]
    else:
        chosen = []
    return {
        index: region
        for index in chosen
        if (region := _region(children[index], relative)) is not None
    }


def _region(node, relative):
    start, end = node.extent.start, node.extent.end
    path = relative(start.file)
    if path is None:
        return None
    return f"{node.kind.name}:{path}:{start.line}:{start.column}-{end.line}:{end.column}"


def _extent_source(start, end) -> str:
    if start.file is None or end.file is None or start.file.name != end.file.name:
        return ""
    return Path(start.file.name).read_bytes()[start.offset:end.offset].decode(errors="replace")


def _written(location) -> str:
    """The identifier at a location as the source spells it; headers may turn memcpy into
    __builtin___memcpy_chk, and the agent reads the source."""
    if location.file is None:
        return ""
    match = IDENT.match(_source(location.file.name), location.offset)
    return match.group() if match else ""


@cache
def _source(path: str) -> str:
    return Path(path).read_bytes().decode("latin-1")  # one character per byte keeps offsets


def _qualified(cursor) -> str:
    parts, parent = [cursor.spelling], cursor.semantic_parent
    while parent is not None and parent.kind != ci.CursorKind.TRANSLATION_UNIT:
        if parent.spelling:
            parts.append(parent.spelling)
        parent = parent.semantic_parent
    return "::".join(reversed(parts))

"""Sinks, sources, backward slices and forward taint over sift.dataflow (ADR 0027).

A sink is a source location whose operands decide a memory access: a subscript, a
dereference of pointer arithmetic, an array-new or variable-length-array size, the
sink arguments of a library model (lengths, sizes, destinations, formats), and integer
conversions and arithmetic whose data feeds one of those. Configuration-specific
occurrences of the same location join into one sink with a stable id, as in
sift.candidates. A slice is every source span the sink's operands depend on, with the
reason each span is there, and the relations the analysis could not compute.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from sift.candidates import _digest
from sift.dataflow import Program, _keys

CHARS_PER_TOKEN = 1.8  # C source characters per Jev input token (Expat R_2_5_0, 2026-09-28; sift.cli)
# Entry points whose arguments come from outside: model-style argument keys ("N", "*N").
ENTRY_POINTS = {"LLVMFuzzerTestOneInput": ("*0", "1"), "main": ("0", "1", "*1")}
FEEDING_SINKS = {"integer conversion", "integer arithmetic"}


@dataclass(frozen=True)
class Sink:
    id: str
    kind: str       # subscript | dereference of pointer arithmetic | array new size |
                    # variable-length array size | call | integer conversion | integer arithmetic
    detail: str     # e.g. "memcpy: argument 2 length" or "narrowing int to short"
    function: str   # Function.id
    path: str
    line: int
    column: int
    end_line: int
    end_column: int
    code: str
    configs: tuple[str, ...]
    starts: tuple = field(default=(), repr=False, compare=False)  # (variant, vertex) in the Program


@dataclass(frozen=True)
class Span:
    id: str
    path: str
    start_line: int
    end_line: int
    function: str             # Function.id; "" for the definition of a global
    configs: tuple[str, ...]
    reasons: tuple[str, ...]  # e.g. "reaching definition", "control dependence", "argument at caller"
    distance: int             # dependence edges from the sink (from the source for taint)
    parent: str | None        # the span through which the traversal first reached this one
    context: tuple[str, ...] = ()  # spans needed to read this one: signature, enclosing branches


@dataclass(frozen=True)
class Unresolved:
    kind: str    # external callee without model | unresolved indirect call | indirect call by signature |
                 # virtual call | no callers | aliasing not modeled (unnamed locations) |
                 # approximate control flow | path depth bound | summary round bound | unmodeled |
                 # token budget cut | traversal bound | over budget
    detail: str
    function: str | None
    path: str | None
    line: int | None


@dataclass(frozen=True)
class Slice:
    sink: Sink
    spans: tuple[Span, ...]            # in file and line order
    unresolved: tuple[Unresolved, ...]
    models: tuple[str, ...]            # library models the slice went through
    dropped: tuple[Span, ...] = ()     # spans a token budget cut removed


@dataclass(frozen=True)
class Source:
    id: str
    kind: str      # entry point parameter | named function parameter | library model
    detail: str
    function: str
    path: str
    line: int
    configs: tuple[str, ...]
    starts: tuple = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class Flow:
    sink: Sink
    path: tuple[Span, ...]  # from the source to the sink


@dataclass(frozen=True)
class Taint:
    source: Source
    flows: tuple[Flow, ...]
    unresolved: tuple[Unresolved, ...]


def tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def sinks(program: Program) -> list[Sink]:
    """Every sink, joined across configurations."""
    groups = {}
    for v in program.variants:
        if program.rep[v.index] != v.index:
            continue  # an equal variant stands for it
        found = program.memory_sinks(v)
        feeding = None
        for slot, kind, detail, *extent in v.ops:
            if kind not in FEEDING_SINKS:
                continue
            if feeding is None:
                feeding = program.feeding(v)
            port = v.call_port(slot, "in")
            vertex = ("in", *port, None) if port else slot
            if vertex in feeding:
                found.append(([vertex], kind, detail, tuple(extent), v.slot_node[slot]))
        for vertices, kind, detail, extent, node in found:
            path = v.ir["files"][v.nodes[node].file]
            # configurations may spell the types or extents differently; the start identifies it
            key = (v.function, path, extent[0], extent[1], kind)
            entry = groups.setdefault(key, [set(), [], extent, set()])
            entry[0].update(program.configs_of[v.index])
            entry[1] += [(v.index, w) for w in vertices]
            entry[3].add(detail)
            if extent[5] - extent[4] > entry[2][5] - entry[2][4]:
                entry[2] = extent
    built = []
    for (function, path, line, column, kind), (configs, starts, extent, details) in groups.items():
        identity = {"function": function, "path": path, "start": [line, column], "kind": kind}
        built.append(Sink("sink:" + _digest(identity), kind, " | ".join(sorted(details)), function, path,
                          line, column, extent[2], extent[3], _code(program.root, path, extent),
                          tuple(sorted(configs)), tuple(dict.fromkeys(starts))))
    return sorted(built, key=lambda s: (s.path, s.line, s.column, s.id))


def slice_of(program: Program, sink: Sink, budget: int | None = None) -> Slice:
    """The backward slice of a sink: what its operands depend on, across calls.

    With a token `budget`, exploring stops after the first distance at which the lines found
    exceed twice what the budget can show; `cut` to the same budget afterwards. A
    whole-program slice can otherwise reach most of a program through its callers."""
    stop, explored = None, []
    if budget is not None:
        lines, size = set(), [0]

        def stop(level, added):
            for vi, x in added:
                n = program.node_of(vi, x)
                if n is not None:
                    v = program.variants[vi]
                    _, file, first, last, _ = v.nodes[n]
                    path = v.ir["files"][file]
                    for line in range(first, last + 1):
                        if (path, line) not in lines:
                            lines.add((path, line))
                            size[0] += len(_line(program.root, path, line)) + 1
            if size[0] > 2 * budget * CHARS_PER_TOKEN:
                explored.append(level)
                return True
            return False
    seen = program.backward(sink.starts, stop)
    spans = _Spans(program)
    unresolved, models, entries = set(), set(), defaultdict(set)
    if explored:
        unresolved.add(Unresolved("traversal bound", f"explored to distance {explored[0]} for a "
                                  f"{budget}-token budget; farther dependences were not computed",
                                  None, None, None))
    for (vi, x), (distance, kind, parent) in seen.items():
        v = program.variants[vi]
        spans.vertex(vi, x, distance, _reason(program, vi, x, kind, parent), parent, seen)
        if type(x) is tuple and x[0] in ("in", "out"):
            target = program.targets[(vi, x[1])]
            if target.kind == "model":
                models.add(target.model)
            unresolved |= _call_unresolved(program, v, x[1])
        elif type(x) is tuple and x[0] == "fin" and not program.callers.get(v.function):
            entries[vi].add(_key_text(program, x[1]))
        if v.function in program.bounded:
            unresolved.add(_at(program, v, 0, "summary round bound",
                               f"the summary of {program.functions[v.function].name} stopped at the round bound"))
        if program.widens(v, x):
            unresolved.add(_at(program, v, program.node_of(vi, x), "path depth bound",
                               f"field paths through a call in {program.functions[v.function].name} were widened"))
    for vi, keys in entries.items():
        v = program.variants[vi]
        unresolved.add(_at(program, v, 0, "no callers",
                           f"{program.functions[v.function].name} has no known callers; values of "
                           f"{', '.join(sorted(keys))} are not traced further"))
    spans.finish(seen)
    unresolved |= spans.notes()
    return Slice(sink, spans.result(), tuple(sorted(unresolved, key=_unresolved_order)),
                 tuple(sorted(models)))


def cut(program: Program, s: Slice, budget: int) -> Slice:
    """Keep the spans nearest to the sink that fit `budget` tokens when rendered.

    Spans are taken by dataflow distance, ties by id. After the first span that does not
    fit, only spans whose lines are already shown are added. What is dropped is reported."""
    by_id = {span.id: span for span in s.spans}
    order = sorted(s.spans, key=lambda span: (span.distance, span.id))
    kept, lines, added = {}, set(), []  # added: (distance, ids) per kept span with its context
    size, full = 0, False
    for span in order:
        if span.id in kept:
            continue
        bundle = [span] + [by_id[i] for i in span.context if i in by_id and i not in kept]
        new = {(b.path, line) for b in bundle for line in range(b.start_line, b.end_line + 1)} - lines
        cost = sum(len(_line(program.root, path, line)) + 1 for path, line in new) + (8 if new else 0)
        if span.distance == 0 or not new or (not full and size + cost <= budget * CHARS_PER_TOKEN):
            kept.update((b.id, b) for b in bundle)
            added.append((span.distance, [b.id for b in bundle]))
            lines |= new
            size += cost
        else:
            full = True
    result = _trimmed(program, s, list(kept.values()))
    while tokens(render(program, result)) > budget and added and added[-1][0] > 0:
        for i in added.pop()[1]:  # the estimate missed: undo the last additions
            del kept[i]
        result = _trimmed(program, s, list(kept.values()))
    shown = tokens(render(program, result))
    if shown > budget:  # the sink's own lines are always kept
        note = Unresolved("over budget", f"the sink and its signature alone render {shown} tokens, "
                          f"over the {budget}-token budget", None, None, None)
        result = Slice(result.sink, result.spans, result.unresolved + (note,), result.models, result.dropped)
    return result


def _trimmed(program: Program, s: Slice, kept) -> Slice:
    ids = {span.id for span in kept}
    dropped = sorted((span for span in s.spans if span.id not in ids), key=lambda span: (span.distance, span.id))
    if not dropped:
        return s
    frontier = [span for span in dropped if span.parent is None or span.parent in ids]
    shown = ", ".join(f"{span.path}:{span.start_line}" for span in frontier[:10])
    detail = (f"{len(dropped)} of {len(s.spans)} spans dropped from distance {dropped[0].distance}; "
              f"{len(frontier)} on the frontier: {shown}" + (", ..." if len(frontier) > 10 else ""))
    # keep what the analysis could not compute about the code still shown
    lines = {(span.function, line) for span in kept for line in range(span.start_line, span.end_line + 1)}
    functions = {span.function for span in kept}
    unresolved = tuple(u for u in s.unresolved
                       if u.function is None or (u.function in functions and
                                                 (u.line is None or (u.function, u.line) in lines
                                                  or u.kind in ("no callers", "aliasing not modeled",
                                                                "path depth bound", "summary round bound"))))
    note = Unresolved("token budget cut", detail, None, None, None)
    return Slice(s.sink, tuple(sorted(kept, key=_span_order)), unresolved + (note,), s.models, tuple(dropped))


def render(program: Program, s: Slice) -> str:
    """Source text of a slice: each function's lines in file order with `...` for gaps,
    the sink marked, and the relations the analysis could not compute listed after."""
    lines = defaultdict(set)
    for span in s.spans:
        lines[(span.path, span.function)].update(range(span.start_line, span.end_line + 1))
    out, last_path = [], None
    for path, function in sorted(lines, key=lambda k: (k[0], min(lines[k]), k[1])):
        if path != last_path:
            out.append(f"// {path}")
            last_path = path
        text = _lines(program.root / path)
        previous = None
        for line in sorted(lines[(path, function)]):
            if line > len(text):
                continue
            row = text[line - 1]
            if previous is not None and line > previous + 1:
                out.append(row[:len(row) - len(row.lstrip())] + "...")
            if (function, path, line) == (s.sink.function, s.sink.path, s.sink.line):
                row += f"  // <- sink: {s.sink.kind}" + (f" ({s.sink.detail})" if s.sink.detail else "")
            out.append(row)
            previous = line
        out.append("")
    by_kind = defaultdict(list)
    for u in s.unresolved:
        detail = u.detail if len(u.detail) <= 200 else u.detail[:200] + "..."
        by_kind[u.kind].append(detail + (f" ({u.path}:{u.line})" if u.path and u.line else ""))
    for kind in sorted(by_kind):
        details = sorted(set(by_kind[kind]))
        shown = details[:5] + ([f"{len(details) - 5} more"] if len(details) > 5 else [])
        out.append(f"// unresolved, {kind}: " + "; ".join(shown))
    return "\n".join(out).rstrip() + "\n"


def sources(program: Program, entry_points: dict = ENTRY_POINTS, functions=()) -> list[Source]:
    """Entry-point parameters, parameters of the named functions (names or ids), and outputs
    of input-reading library models."""
    groups = {}

    def add(v, node, kind, detail, vertex):
        path = v.ir["files"][v.nodes[node].file]
        key = (v.function, path, v.nodes[node].line, kind, detail)
        entry = groups.setdefault(key, [set(), []])
        entry[0].update(program.configs_of[v.index])
        entry[1].append((v.index, vertex))

    for v in program.variants:
        if program.rep[v.index] != v.index:
            continue  # an equal variant stands for it
        f = program.functions[v.function]
        params = program.signatures[v.function][1]
        if f.name in entry_points:
            for spec in entry_points[f.name]:
                for key in _keys(spec, len(params)):
                    if key in v.fin:
                        add(v, 0, "entry point parameter", f"{f.name} {spec}", ("fin", key, None))
        elif f.name in functions or f.id in functions:
            for key in v.fin:
                if key[0] in ("arg", "arg*") and key[1] >= 0:
                    add(v, 0, "named function parameter", f"{f.name} {_key_text(program, key)}",
                        ("fin", key, None))
        for c, call in enumerate(v.calls):
            target = program.targets[(v.index, c)]
            if target.kind != "model":
                continue
            for spec in program.models[target.model].get("sources", ()):
                for key in _keys(spec, len(call.args)):
                    if key in call.outs:
                        add(v, call.node, "library model", f"{target.model} {spec}", ("out", c, key, None))
    built = []
    for (function, path, line, kind, detail), (configs, starts) in groups.items():
        identity = {"function": function, "path": path, "line": line, "kind": kind, "detail": detail}
        built.append(Source("source:" + _digest(identity), kind, detail, function, path, line,
                            tuple(sorted(configs)), tuple(dict.fromkeys(starts))))
    return sorted(built, key=lambda s: (s.path, s.line, s.id))


def taint(program: Program, source: Source, sinks: list[Sink]) -> Taint:
    """The sinks data from a source reaches, each with one path of spans to it."""
    index = defaultdict(list)
    for sink in sinks:
        for start in sink.starts:
            index[start].append(sink)
    seen = program.forward(source.starts)
    reached = {}
    unresolved = set()
    for key in seen:
        for sink in index.get(key, ()):
            reached.setdefault(sink.id, (sink, key))
        vi, x = key
        if type(x) is tuple and x[0] == "in":
            unresolved |= _call_unresolved(program, program.variants[vi], x[1])
    flows = []
    for sink, key in sorted(reached.values(), key=lambda pair: pair[0].id):
        chain = []
        while key is not None:
            chain.append(key)
            key = seen[key][2]
        spans = _Spans(program)
        for distance, (vi, x) in enumerate(reversed(chain)):
            spans.vertex(vi, x, distance, _reason(program, vi, x, *seen[(vi, x)][1:]), None, seen)
        flows.append(Flow(sink, tuple(sorted(spans.result(), key=lambda s: (s.distance, s.id)))))
    return Taint(source, tuple(flows), tuple(sorted(unresolved, key=_unresolved_order)))


# ---- spans -------------------------------------------------------------------------------

class _Spans:
    def __init__(self, program: Program):
        self.program = program
        self.spans = {}       # (function, path, start, end) -> [configs, reasons, distance, parent key]
        self.context = defaultdict(set)  # span key -> keys of the spans needed to read it
        self.of_vertex = {}   # (variant, vertex) -> span key
        self.visited = defaultdict(dict)  # variant -> node -> (distance, span key)

    def add(self, v, key_lines, distance, reason, parent):
        function = v.function
        key = (function, *key_lines)
        entry = self.spans.get(key)
        if entry is None:
            self.spans[key] = [set(self.program.configs_of[v.index]), {reason}, distance, parent]
        else:
            entry[0].update(self.program.configs_of[v.index])
            entry[1].add(reason)
            if distance < entry[2]:
                entry[2], entry[3] = distance, parent
        return key

    def node_lines(self, v, n):
        kind, file, line, end, _ = v.nodes[n]
        path = v.ir["files"][file]
        if kind == "entry":
            first, body, _ = v.ir["header"]
            return (path, first, body)
        return (path, line, end)

    def vertex(self, vi, x, distance, reason, parent, seen):
        v = self.program.variants[vi]
        if type(x) is tuple and (x[0] in ("vg", "gnode") or (x[0] == "fin" and x[1][0] == "global")):
            g = x[-1] if x[0] in ("vg", "gnode") else x[1][1]
            name, path, first, last = self.program.globals.get(g, (None, None, 0, 0))
            if path:
                key = ("", path, first, last)
                entry = self.spans.setdefault(key, [set(), {"global definition"}, distance + 1, None])
                entry[0].update(self.program.configs_of[v.index])
        n = self.program.node_of(vi, x)
        if n is None or (n == v.exit and v.nodes[n].kind == "exit"):
            return
        parent_key = self.parent(parent, seen)
        key = self.add(v, self.node_lines(v, n), distance, reason, parent_key)
        self.of_vertex[(vi, x)] = key
        if n not in self.visited[vi] or distance < self.visited[vi][n][0]:
            self.visited[vi][n] = (distance, key)

    def parent(self, parent, seen):
        while parent is not None:
            if parent in self.of_vertex:
                return self.of_vertex[parent]
            parent = seen[parent][2] if parent in seen else None
        return None

    def finish(self, seen):
        """Exits of included guards, enclosing branch lines and function signatures."""
        for vi, nodes in list(self.visited.items()):
            v = self.program.variants[vi]
            controlled = v.controlled()
            for n, (distance, key) in sorted(nodes.items()):
                kind, file, line, end, ctx = v.nodes[n]
                # a guard: the branches leading to included code, exits on the others, and
                # the jumps that shape its arms (break, continue, goto and the goto's label)
                taken = {branch for m, branch in controlled.get(n, ()) if m in nodes}
                for m, branch in controlled.get(n, ()):
                    if not taken or m in nodes:
                        continue
                    reason = None
                    if v.nodes[m].kind == "jump":
                        reason = "branch structure" if branch in taken else "guard exit"
                    elif branch not in taken and (v.nodes[m].kind == "return" or m in v.ends):
                        reason = "guard exit"
                        c = v.call_at.get(m)
                        if c is not None and "noreturn" not in v.calls[c].flags:
                            reason = "guard exit (callee inferred not to return)"
                    if reason is None:
                        continue
                    exit_key = self.add(v, self.node_lines(v, m), distance + 1, reason, key)
                    self.context[exit_key] |= self.anchors(v, m, distance + 1, exit_key)
                    for label in v.succ[m] if v.nodes[m].kind == "jump" else ():
                        if v.nodes[label].kind == "label":  # where a goto goes
                            self.context[exit_key].add(self.add(v, self.node_lines(v, label), distance + 1,
                                                                "branch structure", exit_key))
                self.context[key] |= self.anchors(v, n, distance, key)
        by_function = defaultdict(list)
        for key in self.spans:
            if key[0]:
                by_function[key[0]].append(key)
        for function, keys in by_function.items():
            v = self.program.of[function][0]
            first, body, _ = v.ir["header"]
            distance = min(self.spans[key][2] for key in keys)
            header = self.add(v, (v.ir["files"][v.nodes[0].file], first, body), distance, "function signature",
                              None)
            for key in keys:
                if key != header:
                    self.context[key].add(header)
                    self.spans[header][0].update(self.spans[key][0])  # in every configuration shown

    def anchors(self, v, n, distance, key) -> set:
        kind, file, line, end, ctx = v.nodes[n]
        path = v.ir["files"][file]
        return {self.add(v, (path, anchor, anchor), distance, "branch structure", key)
                for anchor in v.ir["contexts"][ctx] if not line <= anchor <= end}

    def notes(self) -> set:
        found = set()
        for vi, nodes in self.visited.items():
            v = self.program.variants[vi]
            for kind, line, detail in v.ir["notes"]:
                # what the lowering did not model anywhere in a function can change what it reads
                found.add(Unresolved(kind, detail, v.function, v.ir["files"][0], line or None))
        return found

    def result(self) -> tuple[Span, ...]:
        built = []
        for key, (configs, reasons, distance, parent) in self.spans.items():
            function, path, start, end = key
            built.append(Span(_span_id(*key), path, start, end, function,
                              tuple(sorted(configs)), tuple(sorted(reasons)), distance,
                              _span_id(*parent) if parent else None,
                              tuple(sorted(_span_id(*k) for k in self.context.get(key, ()) if k != key))))
        return tuple(sorted(built, key=_span_order))


def _span_id(function, path, start, end) -> str:
    return "span:" + _digest({"function": function, "path": path, "start": start, "end": end})


def _span_order(span):
    return (span.path, span.start_line, span.end_line, span.function, span.id)


def _unresolved_order(u):
    return (u.kind, u.function or "", u.path or "", u.line or 0, u.detail)


def _reason(program, vi, x, kind, parent=None) -> str:
    if kind in ("sink", "source"):
        return kind
    if kind == "d" and parent is not None and type(parent[1]) is int:
        port = program.variants[parent[0]].slot_port[parent[1]]
        if port is not None and port[0] == "fout":  # the first statements inside a callee
            return "callee return" if port[1] == ("ret",) else "callee side effect"
    if kind == "h" or (kind == "c" and type(x) is int and x in program.variants[vi].halting):
        return "callee may not return depending on argument"
    if kind == "w":
        return "a call may write a local whose address escaped"
    if kind == "c":
        return "control dependence"
    if kind == "a":
        return "argument at caller"
    if kind == "u":
        return "indirect call (uncertain target)"
    if kind == "x":
        return "external callee without model"
    if kind == "g":
        return "global written elsewhere"
    if kind == "m":
        return f"library model {program.targets[(vi, x[1])].model}" if type(x) is tuple else "library model"
    if kind == "s":
        return "callee summary"
    v = program.variants[vi]
    port = v.slot_port[x] if type(x) is int else None
    if (port is not None and port[0] == "fout") or (type(x) is tuple and x[0] == "out"):
        key = port[1] if port is not None else x[2]
        return "callee return" if key == ("ret",) else "callee side effect"
    if type(x) is tuple and x[0] == "fin":
        return "function entry"
    return "reaching definition"


def _call_unresolved(program, v, c) -> set:
    target = program.targets[(v.index, c)]
    call = v.calls[c]
    found = set()
    name = target.name or call.written
    if target.kind == "external":
        found.add(_at(program, v, call.node, "external callee without model", name))
    elif target.kind == "unresolved":
        found.add(_at(program, v, call.node, "unresolved indirect call", name or "function pointer"))
    elif target.kind == "indirect":
        found.add(_at(program, v, call.node, "indirect call by signature",
                      f"{name or 'function pointer'}: {len(target.functions)} candidates; the list may be "
                      "incomplete, casts between function pointer types are not matched"
                      + ("" if target.summarized else "; summarized as an unknown callee")))
    bounded = sorted({program.functions[f].name for f in target.functions if f in program.bounded})
    if bounded:
        found.add(_at(program, v, call.node, "summary round bound",
                      f"{', '.join(bounded)}: summaries hit the round bound; the call is taken as an unknown callee"))
    elif any(f in program.reaches_bound for f in target.functions):
        found.add(_at(program, v, call.node, "summary round bound",
                      f"{name}: calls into a component whose summaries hit the round bound; "
                      "those calls are taken as unknown callees"))
    for flag in call.flags:
        if flag.startswith("same object:"):
            _, i, j = flag.split(":")
            found.add(_at(program, v, call.node, "same object for two parameters",
                          f"{name}: arguments {i} and {j} point to one object; inside the callee, reads "
                          "through either also depend on writes through the other"))
    if "virtual" in call.flags:
        found.add(_at(program, v, call.node, "virtual call", f"{name}: overriders are not resolved"))
    return found


def _at(program, v, node, kind, detail) -> Unresolved:
    return Unresolved(kind, detail, v.function, v.ir["files"][v.nodes[node].file], v.nodes[node].line)


def _key_text(program, key) -> str:
    if key[0] == "global":
        return "global " + program.globals.get(key[1], (key[1],))[0]
    if key[0] in ("arg", "arg*"):
        prefix = "*" if key[0] == "arg*" else ""
        return f"{prefix}this" if key[1] == -1 else f"{prefix}argument {key[1]}"
    return key[0]


def _code(root: Path, path: str, extent) -> str:
    line, _, end_line, _, start, end = extent
    data = (root / path).read_bytes()
    if end > start:
        return data[start:end].decode(errors="replace")
    text = _lines(root / path)
    return text[line - 1].strip() if line <= len(text) else ""


def _line(root: Path, path: str, line: int) -> str:
    text = _lines(root / path)
    return text[line - 1] if 0 < line <= len(text) else ""


@cache
def _lines(path: Path) -> list[str]:
    """Lines as libclang counts them: only \\n ends a line (str.splitlines also splits at \\f)."""
    return [line.removesuffix("\r") for line in path.read_text(errors="replace").split("\n")]

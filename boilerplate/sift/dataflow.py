"""Dataflow over C/C++ functions from libclang: CFGs, dependences and summaries (ADR 0027).

Workers lower every function definition one configuration sees into plain data (`lower`):
CFG nodes with their source lines, def/use slots over access paths, data dependences from
reaching definitions and control dependences from post-dominators. `program` joins the
configuration-specific bodies of each function, resolves calls (direct; indirect through
address-taken functions with a compatible signature, flagged as uncertain; external through
a library model, or conservatively without one) and computes summaries bottom-up over
call-graph SCCs to a fixpoint. `Program.backward` and `Program.forward` traverse the
result; sift.slices turns traversals into slices and taint flows.

An access path names memory: (base, selector, ...). Bases are locals and parameters
("name@offset"), globals and static locals ("g:" + USR), temporaries ("$3"), "$ret",
"$this" and "$va" (variadic arguments). Selectors are ".field", "*" (through a pointer,
offset-insensitive) and "[]" (an element of an array variable, index-insensitive). A
trailing "~" covers everything below; paths deeper than MAX_SELECTORS widen to a prefix,
and field paths in summaries deeper than SUMMARY_SELECTORS.

Inside a function reaching definitions are flow-sensitive, and aliasing is over-approximated
flow-insensitively: memory that a pointer copy, a stored pointer, an address taken or an arm
of `?:` makes reachable from two paths is one object for the whole function, named after a
parameter's or global's memory where possible so that writes through local aliases reach the
summary. A pointer a call returns may point into memory an argument points to: where that
memory could hold the result's type (the whole of untyped or equal-typed memory, else a member
of that type). Struct copies, by-value arguments and struct returns carry everything below the
copied object. Across functions, a global the function does not assign itself is read as its value at
entry or as any write to it anywhere (flow-insensitive); per-call channels for every global a
callee may write made summaries grow with the square of the globals in libxml-sized code.

What the analysis does not see is recorded, never assumed safe: function-level notes
(approximate control flow, widened paths, unmodeled constructs, writes through unnamed
locations) and, per call, unresolved or external targets.
"""

import ctypes
import hashlib
import pickle
from array import array
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import clang.cindex as ci

from sift.code import Body, Function, Scan

CK, TK, BO = ci.CursorKind, ci.TypeKind, ci.BinaryOperator
MAX_SELECTORS = 4  # selectors an access path keeps before widening to "prefix ~"
SUMMARY_SELECTORS = 2  # selectors a field path keeps in summaries (p->f, p->f->g) before widening
MAX_ROUNDS = 8     # summaries per function, on average, a recursive call-graph SCC may take
EDGE_CACHE = 1_000_000  # vertices whose backward edges are kept between slices of one program
CALL_CACHE = 500_000  # per-call facts kept over callees whose summaries are final
INDEXED = 64          # call inputs with this many dependences get an index by field (_narrow)
INDEX_CACHE = 5_000_000  # dependences indexed at a time
# An indirect call with more signature-compatible candidates than this is summarized as an
# unknown callee (every input to every output); slices and taint still enter every candidate.
# Through candidates' summaries, libxml's xmlFree alone joined 3,878 GraphicsMagick functions
# into one recursive component that did not converge in minutes.
MAX_CANDIDATES = 16

FUNCTIONS = {CK.FUNCTION_DECL, CK.CXX_METHOD, CK.CONSTRUCTOR, CK.DESTRUCTOR,
             CK.CONVERSION_FUNCTION, CK.FUNCTION_TEMPLATE}
METHODS = {CK.CXX_METHOD, CK.CONSTRUCTOR, CK.DESTRUCTOR, CK.CONVERSION_FUNCTION}
ARRAYS = {TK.CONSTANTARRAY, TK.INCOMPLETEARRAY, TK.VARIABLEARRAY, TK.DEPENDENTSIZEDARRAY}
REFERENCES = {TK.LVALUEREFERENCE, TK.RVALUEREFERENCE}
SIGNED = {TK.CHAR_S, TK.SCHAR, TK.SHORT, TK.INT, TK.LONG, TK.LONGLONG, TK.INT128}
UNSIGNED = {TK.CHAR_U, TK.UCHAR, TK.USHORT, TK.UINT, TK.ULONG, TK.ULONGLONG, TK.UINT128,
            TK.CHAR16, TK.CHAR32}
CASTS = {CK.CSTYLE_CAST_EXPR, CK.CXX_STATIC_CAST_EXPR, CK.CXX_REINTERPRET_CAST_EXPR,
         CK.CXX_CONST_CAST_EXPR, CK.CXX_DYNAMIC_CAST_EXPR, CK.CXX_FUNCTIONAL_CAST_EXPR}
CONSTANTS = {CK.INTEGER_LITERAL, CK.FLOATING_LITERAL, CK.IMAGINARY_LITERAL, CK.STRING_LITERAL,
             CK.CHARACTER_LITERAL, CK.CXX_BOOL_LITERAL_EXPR, CK.CXX_NULL_PTR_LITERAL_EXPR,
             CK.GNU_NULL_EXPR, CK.CXX_UNARY_EXPR, CK.ADDR_LABEL_EXPR}
ARITHMETIC = {BO.Add: "+", BO.Sub: "-", BO.Mul: "*", BO.Shl: "<<"}
ASSIGNING = {BO.MulAssign: "*", BO.DivAssign: "/", BO.RemAssign: "%", BO.AddAssign: "+",
             BO.SubAssign: "-", BO.ShlAssign: "<<", BO.ShrAssign: ">>", BO.AndAssign: "&",
             BO.XorAssign: "^", BO.OrAssign: "|"}
POST_INC, POST_DEC, PRE_INC, PRE_DEC, ADDRESS_OF, DEREF, LOGICAL_NOT = 1, 2, 3, 4, 5, 6, 10
# Functions that do not return even when their declaration carries no attribute we can see.
NORETURN = {"abort", "exit", "_exit", "_Exit", "quick_exit", "__assert_fail", "__assert_rtn",
            "__builtin_unreachable", "__builtin_trap", "longjmp", "siglongjmp", "_longjmp",
            "err", "errx", "verr", "verrx", "__stack_chk_fail", "__cxa_throw", "pthread_exit"}
CONSTANT_BUILTINS = {"__builtin_constant_p", "__builtin_object_size",
                     "__builtin_dynamic_object_size", "__builtin_offsetof", "__builtin_va_end"}
UNKNOWN = ("$mem", "~")  # a location the lowering could not name
NODE_KINDS = ("entry", "exit", "stmt", "cond", "call", "decl", "return", "jump", "label", "loop", "asm")


# ---- worker: one function in one configuration -------------------------------------------

class _Val(NamedTuple):
    uses: tuple = ()             # access paths read to compute the value
    points: tuple | None = None  # what the value points to, when that memory has a name
    ops: tuple = ()              # sinks and notes for the slot that consumes the value


EMPTY = _Val()


def lower(function, relative, source) -> dict:
    """The CFG, slots and dependences of one function definition as one configuration sees it.

    `relative` maps a libclang file to its path under the target root (or None) and `source`
    returns a file's text with one character per byte, as in sift.cfamily."""
    return _Lower(function, relative, source).run()


class _Lower:
    def __init__(self, function, relative, source):
        self.function, self.relative, self.source = function, relative, source
        self.files, self.file_index = [], {}
        self.nodes, self.succ, self.main, self.ports = [], [], [], []
        self.ops, self.calls, self.notes = [], [], []
        self.addressed, self.globals, self.vars, self.noreturn = set(), {}, {}, {}
        self.labels, self.gotos, self.computed_gotos, self.label_addresses = {}, [], [], set()
        self.loops, self.switches, self.tries, self.returns = [], [], [], []
        self.anchors, self.contexts = [], {}
        self.cur, self.temps, self.returns_value, self.widened = [], 0, False, False
        self.path_ids, self.path_list = {}, []
        self.aliases, self.returned, self.exported = [], defaultdict(list), set()
        self.escapes = []  # (node, path) where an address may leave the function's names

    # -- result ---------------------------------------------------------------------------

    def run(self) -> dict:
        f = self.function
        file, first, last = self.where(f)
        children = list(f.get_children())
        body = next((c for c in reversed(children)
                     if c.kind in (CK.COMPOUND_STMT, CK.CXX_TRY_STMT)), None)
        body_line = body.extent.start.line if body is not None else first
        entry = self.node("entry", where=(file, first, body_line))
        exits = []  # (formal-out key, path its value lives at)
        params = list(f.get_arguments()) or [c for c in children if c.kind == CK.PARM_DECL]
        for i, p in enumerate(params):
            base, reference = self.var(p)
            self.exported.add(base)
            self.port(entry, ("fin", ("arg", i)), defs=(((base,), False),))
            if reference or p.type.get_canonical().kind in (TK.POINTER, *ARRAYS):
                self.port(entry, ("fin", ("arg*", i)), defs=(((base, "*"), False),))
                exits.append((("arg*", i), (base, "*")))
        if f.kind in METHODS and not f.is_static_method():
            self.port(entry, ("fin", ("arg", -1)), defs=((("$this",), False),))
            self.port(entry, ("fin", ("arg*", -1)), defs=((("$this", "*"), False),))
            exits.append((("arg*", -1), ("$this", "*")))
        ftype = f.type.get_canonical()
        variadic = ftype.kind == TK.FUNCTIONPROTO and ftype.is_function_variadic()
        if variadic:
            self.port(entry, ("fin", ("varargs",)), defs=((("$va",), False),))
        if f.kind == CK.CONSTRUCTOR and any(c.kind == CK.MEMBER_REF for c in children):
            self.note("unmodeled", f, "constructor member initializers are not lowered")
        self.cur = [entry]
        if body is not None:
            self.stmt(body)
        exit_ = self.node("exit", where=(file, last, last))
        for n in self.returns:
            self.succ[n].append(exit_)
        for n, name in self.gotos:
            self.succ[n].append(self.labels.get(name, exit_))
        for n in self.computed_gotos:
            targets = [self.labels[name] for name in sorted(self.label_addresses) if name in self.labels]
            self.succ[n].extend(targets or list(self.labels.values()) or [exit_])

        canon = self.alias_classes()
        self.escaped_locals(canon, exit_)
        # Globals this body assigns, also through a local alias, get ports at every call, so
        # callee writes are ordered with its own; the others are read as what reaches the
        # body's entry or any write elsewhere. A write to memory several globals share is a
        # write to each of them.
        main_defs = [canon(p) for defs, _ in self.main for p, _ in defs]
        port_defs = [canon(p) for n, port, defs, _ in self.ports if port[0] != "fin" for p, _ in defs]

        def touched(g, defs):
            stem = canon((g,))
            return any(d[:len(stem)] == stem or stem[:len(d) - (d[-1] == "~")] == d[:len(d) - (d[-1] == "~")]
                       for d in defs)

        written = sorted(g for g in self.globals if touched(g, main_defs))
        modified = sorted(g for g in self.globals if g in written or touched(g, port_defs))
        for g in sorted(self.globals):
            self.port(entry, ("fin", ("global", g)), defs=((canon((g,)), False),))
        for call in self.calls:
            for g in written:
                self.port(call["node"], ("in", ("global", g)), uses=(_wild(canon((g,))),))
                self.port(call["node"], ("out", ("global", g)), defs=((_wild(canon((g,))), False),))
        exits += [(("global", g), (g,)) for g in modified]
        if self.returns_value:
            exits.append((("ret",), ("$ret",)))
        exits = [(key, canon(base)) for key, base in exits]
        for call in self.calls:  # one object passed for two pointer parameters
            pointees = defaultdict(list)
            for n, port, _, uses in self.ports:
                if n == call["node"] and port[0] == "in" and port[1][0] == "arg*" and uses:
                    pointees[uses[0]].append(port[1][1])
            for same in pointees.values():
                call["flags"] += [f"same object:{i}:{j}" for i in same for j in same if i < j]
        deps = self.dependences(exit_, exits)
        control = control_dependences(self.succ, [n[0] for n in self.nodes], exit_)

        slot_of, at_node = {}, defaultdict(list)
        for j, (n, port, _, _) in enumerate(self.ports):
            slot_of[(n, port)] = len(self.nodes) + j
            at_node[n].append((port, len(self.nodes) + j))
        calls = []
        for call in self.calls:
            n = call["node"]
            ins = tuple((port[1], slot) for port, slot in at_node[n] if port[0] == "in")
            outs = tuple((port[1], slot) for port, slot in at_node[n] if port[0] == "out")
            calls.append((n, call["usr"], call["name"], call["written"], tuple(call["args"]),
                          call["signature"], tuple(call["flags"]), ins, outs, call["extent"]))
        ops = [(slot_of[ref] if isinstance(ref, tuple) else ref, *rest) for ref, *rest in self.ops]
        table = {}  # a port tuple once per body; slots refer to it by number
        refs = array("i", (table.setdefault(port, len(table)) for _, port, _, _ in self.ports))
        return {
            "usr": f.get_usr(),
            "signature": _signature(ftype),
            "files": self.files,
            "header": (first, body_line, last),
            # packed rows keep a whole program's bodies in memory: see _Variant for the views
            "kinds": bytes(NODE_KINDS.index(n[0]) for n in self.nodes),
            "spans": array("i", (x for n in self.nodes for x in n[1:4])),
            "context": array("i", (n[4] for n in self.nodes)),
            "contexts": [c for c, _ in sorted(self.contexts.items(), key=lambda item: item[1])],
            "succ": _pack([tuple(dict.fromkeys(s)) for s in self.succ], 1),
            "ports": (tuple(table), array("i", (n for n, _, _, _ in self.ports)), refs),
            "paths": self.path_list,
            "deps": _pack(deps, 3),
            "control": _pack(control, 2),
            "calls": calls,
            "written": written,
            "modified": modified,
            "globals": dict(sorted(self.globals.items())),
            "ops": ops,
            "addressed": sorted(self.addressed),
            "notes": self.notes,
        }

    def alias_classes(self):
        """Join the memory that pointer copies make one: a copy, a stored pointer, an arm of
        `?:`, an address taken or two results of one callee name the same object for the
        whole function (flow-insensitive). Every path is rewritten to its class's
        representative, a parameter's or global's memory where there is one, so writes
        through a local alias are writes to what the caller passed. Returns the rewriting."""
        for pointees in self.returned.values():
            self.aliases += [(pointees[0], other) for other in pointees[1:]]
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in self.aliases:
            parent[find(a)] = find(b)
        changed = True
        while changed:  # what equal pointers point to is one object: if a and b name one
            changed = False  # pointer, *a and *b name one object (fields follow by prefix)
            classes = defaultdict(list)
            for x in list(parent):
                classes[find(x)].append(x)
            for path in list(parent):
                head = path[:-1]
                if path[-1] != "*" or len(head) < 1 or head not in parent:
                    continue
                for other in classes[find(head)]:
                    joined = other + path[-1:]
                    if len(joined) <= MAX_SELECTORS + 1 and find(joined) != find(path):
                        parent[find(joined)] = find(path)
                        changed = True
        classes = defaultdict(list)
        for x in list(parent):
            classes[find(x)].append(x)
        exported = lambda base: base in self.exported or base.startswith(("g:", "$"))
        rep, shared = {}, set()
        for members in classes.values():
            chosen = min(members, key=lambda p: (not (p[0] in self.exported or p[0].startswith("g:")), len(p), p))
            rep.update((m, chosen) for m in members if m != chosen)
            # objects: storage named outright, or memory a parameter, global or call result points
            # to; a local pointer's target is one of the others
            if sum(1 for m in members if "*" not in m[1:] or exported(m[0])) > 1:
                shared.add(chosen)
        cache = {}

        def canon(path):
            found = cache.get(path)
            if found is not None:
                return found
            current = path
            for _ in range(4):
                wild = current[-1] == "~"
                stem = current[:-1] if wild else current
                for k in range(len(stem), 0, -1):
                    target = rep.get(stem[:k])
                    if target is not None:
                        joined = target + stem[k:]
                        if len(joined) > MAX_SELECTORS + 1:
                            joined, wild = joined[:MAX_SELECTORS + 1], True
                        current = joined + (("~",) if wild else ())
                        break
                else:
                    break
            cache[path] = current
            return current

        def strong(path, was):  # a write to memory that may be one of several objects is weak
            if not (was and _strong(path)):
                return False
            return not any(path[:k] in shared for k in range(1, len(path) + 1))

        if rep:
            self.main = [(tuple((canon(p), strong(canon(p), s)) for p, s in defs),
                          tuple(canon(u) for u in uses)) for defs, uses in self.main]
            self.ports = [(n, port, tuple((canon(p), strong(canon(p), s)) for p, s in defs),
                           tuple(canon(u) for u in uses)) for n, port, defs, uses in self.ports]
        return canon if rep else (lambda path: path)

    def escaped_locals(self, canon, exit_):
        """A local whose address goes to a call or is stored through memory may be written by
        any call that can run afterwards: such calls get a weak write of it."""
        locals_ = {}
        for n, path in self.escapes:
            stem = canon(path[:-1] if path[-1] == "~" else path)
            if not stem[0].startswith(("g:", "$")) and stem[0] not in self.exported and "*" not in stem[1:]:
                locals_.setdefault(stem[:1], []).append(n)
        if not locals_:
            return
        nodes = {call["node"] for call in self.calls}
        written = defaultdict(list)  # call node -> escaped locals it may write: one port per call
        for base, starts in sorted(locals_.items()):
            reach = set(starts)
            stack = list(starts)
            while stack:
                for m in self.succ[stack.pop()]:
                    if m not in reach:
                        reach.add(m)
                        stack.append(m)
            for n in reach & nodes:
                written[n].append((base + ("~",), False))
        for n in sorted(written):
            self.port(n, ("out", ("escaped",)), defs=written[n])

    def alias(self, a, b):
        if a is not None and b is not None:
            a, b = (a[:-1] if a[-1] == "~" else a), (b[:-1] if b[-1] == "~" else b)
            if a != b and a[0] != "$mem" and b[0] != "$mem":
                self.aliases.append((a, b))

    def _defs(self):
        yield from (defs for defs, _ in self.main)
        yield from (defs for _, _, defs, _ in self.ports)

    # -- dependences ----------------------------------------------------------------------

    def dependences(self, exit_, exits):
        """Reaching definitions over access paths; data dependences of every slot."""
        n_nodes = len(self.nodes)
        def_slot, def_path = [], []
        gen = [0] * n_nodes
        strong = defaultdict(list)

        def define(n, slot, defs):
            for path, is_strong in defs:
                gen[n] |= 1 << len(def_slot)
                def_slot.append(slot)
                def_path.append(path)
                if is_strong:
                    strong[n].append(path)

        for n, (defs, _) in enumerate(self.main):
            define(n, n, defs)
        for j, (n, _, defs, _) in enumerate(self.ports):
            define(n, n_nodes + j, defs)
        exact, by_base = defaultdict(int), defaultdict(set)
        for d, path in enumerate(def_path):
            exact[path] |= 1 << d
            by_base[path[0]].add(path)
        kill = [0] * n_nodes
        for n, paths in strong.items():
            for p in paths:
                for q in by_base[p[0]]:  # not what was written through a pointer it held
                    if q[:len(p)] == p and not any(s in ("*", "~") for s in q[len(p):]):
                        kill[n] |= exact[q]

        preds = [[] for _ in range(n_nodes)]
        for a, targets in enumerate(self.succ):
            for b in set(targets):
                preds[b].append(a)
        order = _postorder(self.succ, 0)[::-1]
        order += sorted(set(range(n_nodes)) - set(order))
        reach_in, reach_out = [0] * n_nodes, [0] * n_nodes
        changed = True
        while changed:
            changed = False
            for n in order:
                m = 0
                for p in preds[n]:
                    m |= reach_out[p]
                reach_in[n] = m
                out = gen[n] | (m & ~kill[n])
                if out != reach_out[n]:
                    reach_out[n] = out
                    changed = True

        masks = {}

        def overlapping(u):
            mask = masks.get(u)
            if mask is None:
                mask = 0
                for q in by_base.get(u[0], ()):
                    if _overlap(u, q):
                        mask |= exact[q]
                masks[u] = mask
            return mask

        def resolve(n, uses, use_is_port):
            found = []
            for u in uses:
                m = reach_in[n] & overlapping(u)
                while m:
                    low = m & -m
                    d = low.bit_length() - 1
                    m ^= low
                    t = def_slot[d]
                    if use_is_port or t >= n_nodes:
                        found.append((t, self.path_id(u), self.path_id(def_path[d])))
                    else:
                        found.append((t, -1, -1))
            return tuple(dict.fromkeys(found))

        deps = [resolve(n, uses, False) for n, (_, uses) in enumerate(self.main)]
        deps += [resolve(n, uses, port[0] == "in") for n, port, _, uses in self.ports]
        fins = {n_nodes + j for j, (n, port, _, _) in enumerate(self.ports) if port[0] == "fin"}
        for key, base in exits:
            u = base + ("~",)
            groups = defaultdict(list)
            m = reach_in[exit_] & overlapping(u)
            while m:
                low = m & -m
                d = low.bit_length() - 1
                m ^= low
                path = def_path[d]
                stem = path[:-1] if path[-1] == "~" else path
                if def_slot[d] in fins or len(stem) < len(base) or stem[:len(base)] != base:
                    continue  # a value at entry, or the pointer itself was reassigned
                groups[path[len(base):]].append(d)
            for rel in sorted(groups):
                self.port(exit_, ("fout", key, rel))
                deps.append(tuple((def_slot[d], self.path_id(u), self.path_id(def_path[d]))
                                  for d in groups[rel]))

        return deps

    def path_id(self, path) -> int:
        found = self.path_ids.get(path)
        if found is None:
            found = self.path_ids[path] = len(self.path_list)
            self.path_list.append(path)
        return found

    # -- building blocks ------------------------------------------------------------------

    def where(self, cursor):
        start, end = cursor.extent.start, cursor.extent.end
        file = start.file
        if file is None:
            return (0, 0, 0)
        name = file.name
        index = self.file_index.get(name)
        if index is None:
            path = self.relative(file)
            if path is None and self.files:
                index = 0
            else:
                index = len(self.files)
                self.files.append(path or "")
            self.file_index[name] = index
        line = start.line
        end_file = end.file
        last = end.line if end_file is not None and end_file.name == name and end.line >= line else line
        return (index, line, last)

    def extent(self, cursor):
        """(line, column, end line, end column, start offset, end offset); inside a macro
        argument, where the argument is written rather than where the macro is invoked."""
        ext = cursor.extent
        start, end = _spelled(ext.start), _spelled(ext.end)
        if start[0] != end[0] or end[3] < start[3]:
            end = start
        return (start[1], start[2], end[1], end[2], start[3], end[3])

    def context(self) -> int:
        key = tuple(line for frame in self.anchors for line in frame if line is not None)
        return self.contexts.setdefault(key, len(self.contexts))

    def node(self, kind, cursor=None, where=None, uses=(), defs=(), ops=()) -> int:
        n = len(self.nodes)
        self.nodes.append((kind, *(where or self.where(cursor)), self.context()))
        self.succ.append([])
        self.main.append((tuple(defs), tuple(uses)))
        for p in self.cur:
            self.succ[p].append(n)
        self.cur = [n]
        self.attach(n, n, ops)
        if self.tries and kind == "call":
            self.tries[-1].append(n)
        return n

    def port(self, n, port, defs=(), uses=(), ops=()):
        self.ports.append((n, port, tuple(defs), tuple(uses)))
        self.attach(n, (n, port), ops)

    def attach(self, n, slot, ops):
        for kind, detail, extent, sink_uses in ops:
            if sink_uses is None:
                self.ops.append((slot, kind, detail, *extent))
            else:
                port = ("sink", len(self.ops))
                self.ports.append((n, port, (), tuple(sink_uses)))
                self.ops.append(((n, port), kind, detail, *extent))

    def note(self, kind, cursor, detail):
        self.notes.append((kind, cursor.extent.start.line if cursor is not None else 0, detail))

    def temp(self):
        self.temps += 1
        return (f"${self.temps}",)

    def sel(self, path, selector):
        if path[-1] == "~":
            return path
        if len(path) > MAX_SELECTORS:
            if not self.widened:
                self.widened = True
                self.notes.append(("path depth bound", 0, f"access paths deeper than {MAX_SELECTORS} "
                                   "selectors were widened to a prefix"))
            return path + ("~",)
        return path + (selector,)

    def var(self, decl):
        key = decl.hash
        found = self.vars.get(key)
        if found is None:
            reference = decl.type.get_canonical().kind in REFERENCES
            if decl.kind == CK.VAR_DECL and ci.conf.lib.clang_Cursor_hasVarDeclGlobalStorage(decl) == 1:
                base = "g:" + decl.get_usr()
                definition = decl.get_definition() or decl
                start, end = definition.extent.start, definition.extent.end
                self.globals[base] = (decl.spelling, self.relative(start.file) if start.file else None,
                                      start.line, max(start.line, end.line))
            else:
                base = f"{decl.spelling}@{decl.location.offset}"
            found = self.vars[key] = (base, reference)
        return found

    # -- statements -----------------------------------------------------------------------

    def stmt(self, c):
        k = c.kind
        if k == CK.COMPOUND_STMT:
            for child in c.get_children():
                self.stmt(child)
        elif k == CK.DECL_STMT:
            for child in c.get_children():
                if child.kind == CK.VAR_DECL:
                    self.decl(child)
        elif k == CK.IF_STMT:
            self.if_(c)
        elif k in (CK.WHILE_STMT, CK.FOR_STMT, CK.DO_STMT, CK.CXX_FOR_RANGE_STMT):
            self.loop(c, k)
        elif k == CK.SWITCH_STMT:
            self.switch(c)
        elif k in (CK.CASE_STMT, CK.DEFAULT_STMT):
            self.case(c, k)
        elif k == CK.BREAK_STMT:
            self.jump(c, next((frame for frame in reversed(self.loops)), None), 0)
        elif k == CK.CONTINUE_STMT:
            self.jump(c, next((frame for frame in reversed(self.loops) if frame[1] is not None), None), 1)
        elif k == CK.RETURN_STMT:
            children = list(c.get_children())
            if children:
                v = self.value(children[0])
                self.returns_value = True
                uses = v.uses + ((_wild(v.points),) if v.points else ())
                n = self.node("return", c, uses=uses, defs=((("$ret",), True),), ops=v.ops)
            else:
                n = self.node("return", c)
            self.returns.append(n)
            self.cur = []
        elif k == CK.GOTO_STMT:
            n = self.node("jump", c)
            label = next(iter(c.get_children()), None)
            self.gotos.append((n, label.spelling if label is not None else ""))
            self.cur = []
        elif k == CK.INDIRECT_GOTO_STMT:
            v = self.value(next(iter(c.get_children())))
            n = self.node("jump", c, uses=v.uses, ops=v.ops)
            self.computed_gotos.append(n)
            self.note("approximate control flow", c, "computed goto may reach every address-taken label")
            self.cur = []
        elif k == CK.LABEL_STMT:
            line = c.extent.start.line
            n = self.node("label", where=(self.where(c)[0], line, line))
            self.labels[c.spelling] = n
            for child in c.get_children():
                self.stmt(child)
        elif k == CK.CXX_TRY_STMT:
            self.try_(c)
        elif k == CK.NULL_STMT:
            pass
        elif k in (CK.ASM_STMT, CK.MS_ASM_STMT):
            uses, ops, defs = [], [], []
            for child in c.get_children():
                if child.kind.is_expression():
                    v = self.value(child)
                    uses += v.uses
                    ops += v.ops
                    if _strip(child).kind in (CK.DECL_REF_EXPR, CK.MEMBER_REF_EXPR,
                                              CK.ARRAY_SUBSCRIPT_EXPR, CK.UNARY_OPERATOR):
                        defs.append((_wild(self.lvalue(child)[0]), False))  # may be an output
            self.node("asm", c, uses=uses, defs=defs, ops=ops)
            self.note("unmodeled", c, "inline assembly: every operand that names memory is taken as written")
        elif k.is_expression():
            self.discard(self.value(c), c)
        elif k.is_declaration():
            pass  # local types, typedefs, static_assert
        else:
            self.note("unmodeled", c, f"statement {k.name} lowered as its parts")
            for child in c.get_children():
                if child.kind.is_statement() or child.kind.is_expression():
                    self.stmt(child)

    def jump(self, c, frame, which):
        n = self.node("jump", c)
        if frame is None:
            self.returns.append(n)
        else:
            frame[which].append(n)
        self.cur = []

    def discard(self, v, c):
        if v.ops:
            self.node("stmt", c, uses=v.uses, ops=v.ops)

    def decl(self, v):
        base, reference = self.var(v)
        vtype = v.type.get_canonical()
        if base.startswith("g:"):  # a static local: initialized once, read like a global
            init = ci.Cursor.from_result(ci.conf.lib.clang_Cursor_getVarDeclInitializer(v), v)
            if init is not None:  # e.g. a table of handlers that indirect calls go through
                self.addressed.update(r.referenced.get_usr() for r in init.walk_preorder()
                                      if r.kind == CK.DECL_REF_EXPR and r.referenced is not None
                                      and r.referenced.kind in FUNCTIONS)
            return
        if vtype.kind == TK.VARIABLEARRAY:
            size = next((c for c in v.get_children() if c.kind.is_expression()), None)
            if size is not None:
                s = self.value(size)
                self.node("decl", v, uses=s.uses, defs=(((base,), True),),
                          ops=s.ops + (("variable-length array size", v.spelling, self.extent(size), s.uses),))
                return
        init = ci.Cursor.from_result(ci.conf.lib.clang_Cursor_getVarDeclInitializer(v), v)
        if init is None:
            self.node("decl", v, defs=(((base,), True),))
            return
        if reference:
            p, uses, ops = self.lvalue(init)
            self.alias((base, "*"), p)
            self.node("decl", v, uses=uses + (_wild(p),), defs=(((base,), True), ((base, "*"), False)),
                      ops=ops)
            return
        inner = _strip(init)
        if inner.kind == CK.CALL_EXPR and (r := inner.referenced) is not None and r.kind == CK.CONSTRUCTOR:
            self.call(inner, this=(base,))
            return
        val = self.value(init)
        uses = val.uses
        if val.points and vtype.kind == TK.POINTER:
            uses += (_wild(val.points),)  # contents travel with a copied pointer
            self.alias((base, "*"), val.points)
        self.node("decl", v, uses=uses, defs=(((base,), True),), ops=val.ops)

    def if_(self, c):
        children = list(c.get_children())
        i = 0
        init = self.has_init(c, children)  # C++17 `if (init; cond)` with an expression as init
        while i < len(children) - 2 and (children[i].kind in (CK.DECL_STMT, CK.VAR_DECL) or (init and i == 0)):
            self.stmt(children[i]) if children[i].kind != CK.VAR_DECL else self.decl(children[i])
            i += 1
        cond, then = children[i], children[i + 1]
        otherwise = children[i + 2] if len(children) > i + 2 else None
        frame = [c.extent.start.line]
        self.anchors.append(frame)
        yes, no = self.branch(cond)
        self.cur = yes
        self.stmt(then)
        done = self.cur
        self.cur = no
        if otherwise is not None:
            frame.append(self.keyword_line(otherwise, "else"))
            self.stmt(otherwise)
        self.cur = done + self.cur
        self.anchors.pop()

    def has_init(self, c, children) -> bool:
        """Whether an if statement's parentheses hold `init;` before the condition."""
        if len(children) < 3 or children[0].kind in (CK.DECL_STMT, CK.VAR_DECL):
            return False
        start = c.extent.start
        if start.file is None:
            return False
        text = self.source(start.file.name)
        i, depth = text.find("(", start.offset, children[0].extent.start.offset + 1), 0
        while 0 <= i < len(text):
            ch = text[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    return False
            elif ch == ";" and depth == 1:
                return True
            elif ch in "\"'":
                i = _skip_quoted(text, i)
            i += 1
        return False

    def keyword_line(self, c, word) -> int:
        """The line of the keyword that precedes a statement, e.g. `else` on its own line."""
        start = c.extent.start
        if start.file is None:
            return start.line
        text = self.source(start.file.name)
        at = text.rfind(word, max(0, start.offset - 2000), start.offset)
        if at < 0:
            return start.line
        return start.line - text.count("\n", at, start.offset)

    def loop(self, c, k):
        children = list(c.get_children())
        line = c.extent.start.line
        here = self.where(c)
        frame = [line]
        self.anchors.append(frame)
        breaks, continues = [], []
        if k == CK.DO_STMT:
            body, cond = children[0], children[-1]
            top = self.node("loop", where=(here[0], line, line))
            self.loops.append((breaks, continues))
            self.stmt(body)
            self.loops.pop()
            self.cur += continues
            yes, no = self.branch(cond)
            for p in yes:
                self.succ[p].append(top)
            self.cur = no + breaks
            self.anchors.pop()
            return
        body = children[-1]
        if k == CK.CXX_FOR_RANGE_STMT:
            var = next((ch for ch in children if ch.kind == CK.VAR_DECL), None)
            rng = self.value(children[-2])
            source = rng.uses + tuple(_wild(u) for u in rng.uses) + ((_wild(rng.points),) if rng.points else ())
            head = self.node("loop", where=(here[0], line, line))
            test = self.node("cond", children[-2], uses=source, ops=rng.ops)
            yes = no = [test]
            self.cur = yes
            if var is not None:
                self.node("decl", var, uses=source, defs=(((self.var(var)[0],), True),))
        else:
            if k == CK.WHILE_STMT:
                init, cond, step = None, children[-2], None
            else:
                init, cond, step = self.for_parts(c, children)
            if init is not None:
                self.stmt(init)
            head = self.node("loop", where=(here[0], line, line))
            decls = [ch for ch in children[:-1] if ch.kind == CK.VAR_DECL and k == CK.WHILE_STMT]
            for d in decls:  # `while (T x = f())` declares on every iteration
                self.decl(d)
            yes, no = self.branch(cond) if cond is not None else (self.cur, [])
        self.cur = yes
        self.loops.append((breaks, continues))
        self.stmt(body)
        self.loops.pop()
        self.cur += continues
        if k == CK.FOR_STMT and step is not None:
            self.discard(self.value(step), step)
        for p in self.cur:
            self.succ[p].append(head)
        self.cur = list(no) + breaks
        self.anchors.pop()

    def for_parts(self, c, children):
        """(init, condition, increment) of a for statement; libclang omits the empty ones."""
        rest = children[:-1]
        if len(rest) == 3:
            return tuple(rest)
        start = c.extent.start
        text = self.source(start.file.name) if start.file is not None else ""
        semis, depth, i = [], 0, text.find("(", start.offset, children[-1].extent.start.offset)
        if text[start.offset:start.offset + 3] != "for" or i < 0:
            self.note("approximate control flow", c, "for header from a macro: parts guessed by position")
            parts = [None, None, None]
            for ch in rest:
                parts[parts.index(None)] = ch
            return tuple(parts)
        while i < len(text) and len(semis) < 2:
            ch = text[i]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ";" and depth == 1:
                semis.append(i)
            elif ch in "\"'":
                i = _skip_quoted(text, i)
            elif text.startswith("/*", i):
                i = text.find("*/", i + 2) + 1 or len(text)
            elif text.startswith("//", i):
                i = text.find("\n", i) if text.find("\n", i) >= 0 else len(text)
            i += 1
        parts = [None, None, None]
        for ch in rest:
            offset = ch.extent.start.offset
            parts[0 if not semis or offset < semis[0] else 1 if len(semis) < 2 or offset < semis[1] else 2] = ch
        return tuple(parts)

    def switch(self, c):
        children = list(c.get_children())
        for d in children[:-2]:
            self.stmt(d) if d.kind == CK.DECL_STMT else self.decl(d)
        cond, body = children[-2], children[-1]
        v = self.value(cond)
        test = self.node("cond", cond, uses=v.uses, ops=v.ops)
        frame = [c.extent.start.line, None]
        self.anchors.append(frame)
        state = {"node": test, "default": False, "frame": frame}
        breaks = []
        self.switches.append(state)
        self.loops.append((breaks, None))
        self.cur = []
        self.stmt(body)
        self.loops.pop()
        self.switches.pop()
        self.anchors.pop()
        self.cur = self.cur + breaks + ([] if state["default"] else [test])

    def case(self, c, k):
        children = list(c.get_children())
        line = c.extent.start.line
        if not self.switches:
            self.note("unmodeled", c, "case label outside a switch")
        else:
            state = self.switches[-1]
            state["frame"][1] = line
            state["default"] |= k == CK.DEFAULT_STMT
            self.cur = self.cur + [state["node"]]
        self.node("label", where=(self.where(c)[0], line, line))
        if children:
            self.stmt(children[-1])

    def try_(self, c):
        children = list(c.get_children())
        line = c.extent.start.line
        here = self.where(c)
        frame = [line]
        self.anchors.append(frame)
        start = self.node("label", where=(here[0], line, line))
        self.tries.append([start])
        self.stmt(children[0])
        throwers = self.tries.pop()
        done = self.cur
        for handler in children[1:]:
            parts = list(handler.get_children())
            hline = handler.extent.start.line
            frame.append(hline)
            self.cur = list(throwers)
            self.node("label", where=(here[0], hline, hline))
            for part in parts:
                if part.kind == CK.VAR_DECL:
                    self.node("decl", part, defs=(((self.var(part)[0],), True),))
                else:
                    self.stmt(part)
            frame.pop()
            done += self.cur
        self.cur = done
        self.anchors.pop()
        self.note("approximate control flow", c,
                  "try/catch: every call and throw in the try body may enter each handler")

    # -- conditions -----------------------------------------------------------------------

    def branch(self, c, temp=None):
        """Lower a condition; the nodes left on its true and on its false edge."""
        c = _strip(c)
        k = c.kind
        if k == CK.BINARY_OPERATOR:
            op = c.binary_operator
            if op in (BO.LAnd, BO.LOr):
                left, right = list(c.get_children())
                yes, no = self.branch(left, temp)
                self.cur = yes if op == BO.LAnd else no
                yes2, no2 = self.branch(right, temp)
                return (yes2, no + no2) if op == BO.LAnd else (yes + yes2, no2)
        elif k == CK.UNARY_OPERATOR and _unary(c) == LOGICAL_NOT:
            yes, no = self.branch(next(iter(c.get_children())), temp)
            return no, yes
        v = self.value(c)
        n = self.node("cond", c, uses=v.uses, defs=((temp, True),) if temp else (), ops=v.ops)
        return [n], [n]

    # -- expressions ----------------------------------------------------------------------

    def value(self, c) -> _Val:
        k = c.kind
        if k == CK.UNEXPOSED_EXPR or k == CK.PAREN_EXPR:
            children = list(c.get_children())
            if len(children) == 1:
                inner = children[0]
                if k == CK.UNEXPOSED_EXPR and "va_list" in inner.type.spelling and c.type.kind != inner.type.kind:
                    v = self.value(inner)  # va_arg(ap, T)
                    return _Val(v.uses + (("$va", "~"), _wild(v.uses[0]) if v.uses else ("$va",)), None, v.ops)
                v = self.value(inner)
                if k == CK.UNEXPOSED_EXPR and v.uses:
                    detail = _conversion(c.type, inner.type)
                    if detail:
                        v = v._replace(ops=v.ops + (("integer conversion", detail, self.extent(c), None),))
                return v
            return self.union(children)
        if k == CK.DECL_REF_EXPR:
            ref = c.referenced
            if ref is None:
                return EMPTY
            rk = ref.kind
            if rk in (CK.VAR_DECL, CK.PARM_DECL):
                return self.load(c)
            if rk in FUNCTIONS:
                self.addressed.add(ref.get_usr())
            return EMPTY
        if k in (CK.MEMBER_REF_EXPR, CK.ARRAY_SUBSCRIPT_EXPR):
            return self.load(c)
        if k in CONSTANTS:
            if k == CK.ADDR_LABEL_EXPR:
                self.label_addresses.add(c.spelling)
            return EMPTY
        if k == CK.CALL_EXPR:
            return self.call(c)
        if k == CK.BINARY_OPERATOR:
            return self.binary(c)
        if k == CK.COMPOUND_ASSIGNMENT_OPERATOR:
            left, right = list(c.get_children())
            return self.assign(c, left, right, ASSIGNING.get(c.binary_operator, "?"))
        if k == CK.UNARY_OPERATOR:
            return self.unary(c)
        if k == CK.CONDITIONAL_OPERATOR:
            return self.conditional(c)
        if k in CASTS:
            children = [ch for ch in c.get_children() if ch.kind.is_expression()]
            if not children:
                return EMPTY
            v = self.value(children[-1])
            detail = _conversion(c.type, children[-1].type) if v.uses else None
            if detail:
                v = v._replace(ops=v.ops + (("integer conversion", detail, self.extent(c), None),))
            return v
        if k == CK.INIT_LIST_EXPR:
            return self.union(list(c.get_children()))
        if k.name == "StmtExpr":
            return self.statement_expression(c)
        if k == CK.CXX_THIS_EXPR:
            return _Val((("$this",),), ("$this", "*"))
        if k == CK.CXX_THROW_EXPR:
            v = self.union(list(c.get_children()))
            n = self.node("jump", c, uses=v.uses, ops=v.ops)
            (self.tries[-1] if self.tries else self.returns).append(n)
            self.cur = []
            return EMPTY
        if k == CK.CXX_NEW_EXPR:
            return self.new(c)
        if k == CK.CXX_DELETE_EXPR:
            v = self.union(list(c.get_children()))
            self.node("stmt", c, uses=v.uses, ops=v.ops)
            return EMPTY
        if k == CK.LAMBDA_EXPR:
            self.note("unmodeled", c, "lambda body is not analyzed")
            return EMPTY
        if k.is_expression():
            if k != CK.UNEXPOSED_EXPR:
                self.note("unmodeled", c, f"expression {k.name} read as the union of its parts")
            return self.union([ch for ch in c.get_children() if ch.kind.is_expression()])
        return EMPTY

    def union(self, children) -> _Val:
        uses, ops, points = (), (), None
        for child in children:
            if child.kind.is_expression():
                v = self.value(child)
                uses += v.uses
                ops += v.ops
                points = points or v.points
        return _Val(uses, points, ops)

    def load(self, c) -> _Val:
        """The value an lvalue expression reads."""
        path, uses, ops = self.lvalue(c)
        kind = c.type.get_canonical().kind
        if kind in ARRAYS:  # decays to its address
            return _Val(uses, self.sel(path, "[]"), ops)
        if kind == TK.POINTER:
            return _Val(uses + (path,), self.sel(path, "*"), ops)
        if kind == TK.RECORD:  # a struct copy carries what its pointer fields point to
            return _Val(uses + (_wild(path),), None, ops)
        return _Val(uses + (path,), None, ops)

    def lvalue(self, c):
        """(path written or read, uses that locate it, pending ops)."""
        c = _strip(c)
        k = c.kind
        if k == CK.DECL_REF_EXPR:
            ref = c.referenced
            if ref is not None and ref.kind in (CK.VAR_DECL, CK.PARM_DECL):
                base, reference = self.var(ref)
                return ((base, "*") if reference else (base,)), (), ()
            return UNKNOWN, (), ()
        if k == CK.MEMBER_REF_EXPR:
            children = list(c.get_children())
            name = "." + c.spelling
            base = _strip(children[0]) if children else None
            if base is None or base.kind == CK.CXX_THIS_EXPR:
                return self.sel(("$this", "*"), name), (("$this",),), ()
            if base.type.get_canonical().kind == TK.POINTER:
                v = self.value(base)
                return self.sel(v.points or UNKNOWN, name), v.uses, v.ops
            path, uses, ops = self.lvalue(base)
            return self.sel(path, name), uses, ops
        if k == CK.ARRAY_SUBSCRIPT_EXPR:
            base, index = list(c.get_children())
            if base.type.get_canonical().kind in INTEGER_KINDS:
                base, index = index, base
            i = self.value(index)
            btype = _strip(base).type.get_canonical()
            constant = not i.uses
            if btype.kind in ARRAYS and btype.kind != TK.INCOMPLETEARRAY and btype.get_array_size() > 1:
                path, uses, ops = self.lvalue(base)
                path = self.sel(path, "[]")
                sink = not constant
                operand = uses + i.uses
            else:
                v = self.value(base)
                path, uses, ops = v.points or UNKNOWN, v.uses, v.ops
                sink = not (constant and self.literal(index) == 0)
                operand = v.uses + i.uses
            ops = ops + i.ops
            if sink:
                ops += (("subscript", "", self.extent(c), operand),)
            return path, uses + i.uses, ops
        if k == CK.UNARY_OPERATOR and _unary(c) == DEREF:
            operand = next(iter(c.get_children()))
            v = self.value(operand)
            ops = v.ops
            if _arithmetic(_strip(operand)):
                ops += (("dereference of pointer arithmetic", "", self.extent(c), v.uses),)
            return v.points or UNKNOWN, v.uses, ops
        v = self.value(c)
        if v.points is None:
            self.note("aliasing not modeled", c, "access through an expression with no named location")
        return v.points or UNKNOWN, v.uses, v.ops

    def literal(self, c):
        c = _strip(c)
        if c.kind != CK.INTEGER_LITERAL:
            return None
        start, end = c.extent.start, c.extent.end
        if start.file is None:
            return None
        text = self.source(start.file.name)[start.offset:end.offset].rstrip("uUlL")
        try:
            return int(text, 0)
        except ValueError:
            return None

    def binary(self, c) -> _Val:
        op = c.binary_operator
        left, right = list(c.get_children())
        if op == BO.Assign:
            return self.assign(c, left, right, None)
        if op in (BO.LAnd, BO.LOr):
            t = self.temp()
            yes, no = self.branch(c, t)
            self.cur = yes + no
            return _Val((t,))
        if op == BO.Comma:
            self.discard(self.value(left), left)
            return self.value(right)
        a, b = self.value(left), self.value(right)
        ops = a.ops + b.ops
        kind = c.type.get_canonical().kind
        if op in ARITHMETIC and kind in INTEGER_KINDS and (a.uses or b.uses):
            ops += (("integer arithmetic", f"{ARITHMETIC[op]} in {c.type.spelling}", self.extent(c), None),)
        points = (a.points or b.points) if kind == TK.POINTER else None
        return _Val(a.uses + b.uses, points, ops)

    def assign(self, c, left, right, compound) -> _Val:
        r = self.value(right)
        path, uses, ops = self.lvalue(left)
        uses += r.uses
        if compound:
            uses += (path,)
        kind = left.type.get_canonical().kind
        if r.points is not None and kind == TK.POINTER:
            uses += (_wild(r.points),)  # contents travel with a copied pointer
            self.alias(self.sel(path, "*"), r.points)
            if path[0].startswith("g:") or "*" in path[1:]:  # stored where other code can reach it
                self.escapes.append((len(self.nodes), r.points))
        if compound and kind == TK.POINTER:
            uses += (_wild(path),)  # p += k still reaches what was written through p
        ops += r.ops
        if compound in ("+", "-", "*", "<<") and kind in INTEGER_KINDS:
            ops += (("integer arithmetic", f"{compound}= in {left.type.spelling}", self.extent(c), None),)
        if path[0] == "$mem":
            self.note("aliasing not modeled", c, "write through an unnamed location")
        self.node("stmt", c, uses=uses, defs=((path, _strong(path)),), ops=ops)
        return _Val((path,), self.sel(path, "*") if kind == TK.POINTER else None)

    def unary(self, c) -> _Val:
        op = _unary(c)
        operand = next(iter(c.get_children()), None)
        if operand is None:
            return EMPTY
        if op in (POST_INC, POST_DEC, PRE_INC, PRE_DEC):
            path, uses, ops = self.lvalue(operand)
            pointer = operand.type.get_canonical().kind == TK.POINTER
            extra = (_wild(path),) if pointer else ()  # p++ still reaches what was written through p
            self.node("stmt", c, uses=uses + (path,) + extra, defs=((path, _strong(path)),), ops=ops)
            return _Val((path,), self.sel(path, "*") if pointer else None)
        if op == ADDRESS_OF:
            path, uses, ops = self.lvalue(operand)
            return _Val(uses, path, ops)
        if op == DEREF:
            return self.load(c)
        return self.value(operand)

    def conditional(self, c) -> _Val:
        children = list(c.get_children())
        t = self.temp()
        cond, arms = children[0], children[1:]
        yes, no = self.branch(cond)
        pointer = c.type.get_canonical().kind == TK.POINTER
        ends = []
        for edge, arm in zip((yes, no), arms if len(arms) == 2 else [cond, arms[-1]]):
            self.cur = edge
            v = self.value(arm)
            uses = v.uses + ((_wild(v.points),) if pointer and v.points else ())
            if pointer:
                self.alias(self.sel(t, "*"), v.points)
            self.node("stmt", arm, uses=uses, defs=((t, True),), ops=v.ops)
            ends += self.cur
        self.cur = ends
        return _Val((t,), self.sel(t, "*") if pointer else None)

    def statement_expression(self, c) -> _Val:
        compound = next(iter(c.get_children()), None)
        parts = list(compound.get_children()) if compound is not None else []
        for part in parts[:-1]:
            self.stmt(part)
        if parts and parts[-1].kind.is_expression():
            return self.value(parts[-1])
        if parts:
            self.stmt(parts[-1])
        return EMPTY

    def new(self, c) -> _Val:
        children = [ch for ch in c.get_children() if ch.kind.is_expression()]
        tokens = [t.spelling for t in c.get_tokens()]
        array, depth = False, 0
        for t in tokens[1:]:
            if t == "(":
                depth += 1
            elif t == ")":
                depth -= 1
            elif t == "[" and depth == 0:
                array = True
                break
        uses, ops = (), ()
        t = self.temp()
        for i, child in enumerate(children):
            if child.kind == CK.CALL_EXPR and (r := child.referenced) is not None and r.kind == CK.CONSTRUCTOR:
                self.call(child, this=self.sel(t, "*"))
                continue
            v = self.value(child)
            uses += v.uses
            ops += v.ops
            if array and i == 0:
                ops += (("array new size", "", self.extent(child), v.uses),)
        self.node("stmt", c, uses=uses, defs=((t, True),), ops=ops)
        return _Val((t,), self.sel(t, "*"))

    def call(self, c, this=None) -> _Val:
        ref = c.referenced
        direct = ref is not None and ref.kind in FUNCTIONS
        name = ref.spelling if direct else ""
        children = list(c.get_children())
        args = list(c.get_arguments())
        if direct and name in ("__builtin_expect", "__builtin_expect_with_probability") and args:
            return self.value(args[0])
        if direct and name in CONSTANT_BUILTINS:
            return EMPTY
        if direct and name in ("__builtin_va_start", "__builtin_va_copy", "__builtin_c23_va_start"):
            path, uses, ops = self.lvalue(args[0])
            source = ((("$va", "~"),) if name != "__builtin_va_copy"
                      else (_wild(self.lvalue(args[1])[0]),))
            self.node("stmt", c, uses=uses + source, defs=((_wild(path), False),), ops=ops)
            return EMPTY
        own = {a.hash for a in args}
        callee = next((ch for ch in children if ch.hash not in own), None)
        ftype = ref.type.get_canonical() if direct else _function_type(callee)
        params = list(ftype.argument_types()) if ftype is not None and ftype.kind == TK.FUNCTIONPROTO else []
        flags = []
        fn = EMPTY
        this_val = None
        if direct and ref.kind in METHODS and not ref.is_static_method():
            if ref.is_virtual_method():
                flags.append("virtual")
            if this is not None:
                this_val = _Val((), this)
            elif len(args) == len(params) + 1:  # operator call: the object comes first
                obj, args = args[0], args[1:]
                this_val = self._object(obj, obj.type.get_canonical().kind == TK.POINTER)
            elif callee is not None and callee.kind == CK.MEMBER_REF_EXPR:
                parts = list(callee.get_children())
                if parts:
                    this_val = self._object(parts[0], parts[0].type.get_canonical().kind == TK.POINTER)
                else:
                    this_val = _Val((("$this",),), ("$this", "*"))
        elif not direct and callee is not None:
            fn = self.value(callee)
        ins, outs, info, pointers = [], [], [], []
        for i, a in enumerate(args):
            ptype = params[i].get_canonical() if i < len(params) else None
            if ptype is not None and ptype.kind in REFERENCES:
                path, uses, ops = self.lvalue(a)
                v = _Val(uses, path, ops)
                const = ptype.get_pointee().is_const_qualified()
            else:
                stripped = _strip(a)
                if stripped.kind == CK.UNARY_OPERATOR and _unary(stripped) == ADDRESS_OF:
                    path, uses, ops = self.lvalue(next(iter(stripped.get_children())))
                    v = _Val(uses, path, ops)
                else:
                    v = self.value(a)
                atype = (ptype or a.type).get_canonical()
                const = atype.kind == TK.POINTER and atype.get_pointee().is_const_qualified()
            ins.append((("arg", i), v.uses, v.ops))
            if v.points is not None:
                pointers.append((i, v.points, ptype or a.type))
                self.escapes.append((len(self.nodes), v.points))  # the call node made below
                ins.append((("arg*", i), (_wild(v.points),), ()))
                if not const:  # a callee does not write through a pointer to const
                    outs.append((("arg*", i), ((_wild(v.points), False),)))
            info.append((v.points is not None, const, not v.uses))
        if this_val is not None:
            ins.append((("arg", -1), this_val.uses, this_val.ops))
            if this_val.points is not None:
                ins.append((("arg*", -1), (_wild(this_val.points),), ()))
                outs.append((("arg*", -1), ((_wild(this_val.points), False),)))
        if fn.uses or fn.ops:
            ins.append((("fn",), fn.uses, fn.ops))
        n = self.node("call", c)
        for key, uses, ops in ins:
            self.port(n, ("in", key), uses=uses, ops=ops)
        result = EMPTY
        rtype = c.type.get_canonical()
        if rtype.kind != TK.VOID and this is None:
            t = self.temp()
            self.port(n, ("out", ("ret",)), defs=((t, True),))
            result = _Val((t,), self.sel(t, "*") if rtype.kind == TK.POINTER else None)
            if rtype.kind == TK.POINTER:  # a result may point into memory an argument points to
                held = dict((j, p) for j, p, _ in pointers)
                for i, rel in _points_into(name, rtype, pointers):
                    target = held[i]
                    for selector in rel:
                        target = self.sel(target, selector)
                    self.alias(result.points, target)
            if rtype.kind == TK.POINTER:  # one callee called alike twice may return one object
                line, column, end_line, end_column, start, end = self.extent(c)
                text = self.source(c.extent.start.file.name)[start:end] if c.extent.start.file else ""
                if text:  # an allocator called with other arguments returns other memory
                    self.returned[(ref.get_usr() if direct else _written_name(c, self.source), text)].append(
                        result.points)
        for key, defs in outs:
            self.port(n, ("out", key), defs=defs)
        noreturn = direct and self.is_noreturn(ref)
        if noreturn:
            flags.append("noreturn")
        self.calls.append({
            "node": n, "usr": ref.get_usr() if direct else None, "name": name,
            "written": _written_name(c, self.source), "args": info,
            "signature": None if direct or ftype is None else _signature(ftype),
            "flags": flags, "extent": self.extent(c),
        })
        if noreturn:
            self.returns.append(n)
            self.cur = []
        return result

    def _object(self, obj, pointer) -> _Val:
        if pointer:
            return self.value(obj)
        path, uses, ops = self.lvalue(obj)
        return _Val(uses, path, ops)

    def is_noreturn(self, ref) -> bool:
        key = ref.hash
        found = self.noreturn.get(key)
        if found is None:
            found = "noreturn" in ref.type.spelling or (
                ref.spelling in NORETURN and (ref.spelling.startswith("__") or ref.location.is_in_system_header))
            if not found:
                for child in ref.get_children():
                    if child.kind == CK.UNEXPOSED_ATTR or child.kind.name.endswith("_ATTR"):
                        start, end = child.extent.start, child.extent.end
                        if start.file is not None and "noreturn" in self.source(start.file.name)[
                                start.offset:max(end.offset, start.offset + 40)].lower():
                            found = True
                            break
            self.noreturn[key] = found
        return found


INTEGER_KINDS = SIGNED | UNSIGNED | {TK.BOOL}


def _unary(c) -> int:
    return ci.conf.lib.clang_getCursorUnaryOperatorKind(c)


def _strip(c):
    """Look through parentheses and single-child implicit expressions."""
    while c.kind in (CK.PAREN_EXPR, CK.UNEXPOSED_EXPR):
        children = list(c.get_children())
        if len(children) != 1:
            break
        c = children[0]
    return c


def _spelled(location):
    """(file name, line, column, offset) of a location: its spelling inside a macro
    argument written in the same file, its expansion otherwise."""
    file, line, column, offset = location.file, location.line, location.column, location.offset
    if file is None:
        return (None, line, column, offset)
    f, sl, sc, so = ci.c_object_p(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
    ci.conf.lib.clang_getSpellingLocation(location, ctypes.byref(f), ctypes.byref(sl), ctypes.byref(sc),
                                          ctypes.byref(so))
    if so.value > offset and f and ci.File(f).name == file.name:
        return (file.name, sl.value, sc.value, so.value)
    return (file.name, line, column, offset)


def model_name(name: str, models: dict) -> str | None:
    """The model for a declared callee, also through builtin and fortified spellings
    (__builtin___memcpy_chk, __isoc99_sscanf)."""
    tries = [name]
    if name.startswith("__builtin___"):  # fortified: __snprintf_chk has its own layout
        tries += ["__" + name[12:], name[12:].removesuffix("_chk")]
    elif name.startswith(("__builtin_", "__isoc99_", "__isoc23_")):
        tries.append(name.split("_", 3)[-1] if name.startswith("__isoc") else name[10:])
    elif name.startswith("__"):
        tries.append(name[2:].removesuffix("_chk"))
    return next((t for t in tries if t in models), None)


def _points_into(name, rtype, pointers) -> list[tuple[int, tuple]]:
    """(argument, selectors below its memory) a pointer result may point to: as a library
    model says, else where the argument's memory could hold the result's pointee type (see
    _within)."""
    model = model_name(name, MODELS) if name else None
    if model is not None:
        found = []
        for spec in MODELS[model].get("flows", {}).get("ret", ()):
            number = spec.lstrip("*").rstrip("+")
            found += [(i, ()) for i, _, _ in pointers if number.isdigit() and i == int(number)]
        return found
    target = rtype.get_canonical().get_pointee().get_canonical()
    found = []
    for i, _, atype in pointers:
        pointee = atype.get_canonical()
        pointee = (pointee.get_pointee() if pointee.kind in (TK.POINTER, *REFERENCES)
                   else pointee.get_array_element_type()).get_canonical()
        found += [(i, rel) for rel in _within(pointee, target)]
    return found


CHARS = (TK.CHAR_S, TK.CHAR_U, TK.SCHAR, TK.UCHAR)


def _within(outer, inner, depth=0) -> list[tuple]:
    """Selectors below an `outer` object where an `inner` one may start: the whole of untyped
    memory (void, or characters holding bytes of anything) or of memory of the inner type,
    else the struct and union members (also nested) of the inner type, and for an untyped
    inner pointer the array members (buffers). A struct's start or scalar members are not
    joined with an untyped pointer: that conflated the fields of every allocation and
    `char *` result with a `lua_State` argument and made the lua build several times slower."""
    if outer.kind in (TK.VOID, TK.INVALID, *CHARS) or inner.kind == TK.INVALID:
        return [()]
    if _plain(outer) == _plain(inner):
        return [()]
    if outer.kind != TK.RECORD or depth >= MAX_SELECTORS - 1:
        return []
    untyped = inner.kind in (TK.VOID, *CHARS)
    found = []
    for field in outer.get_fields():
        t, rel = field.type.get_canonical(), ("." + field.spelling,)
        while t.kind in ARRAYS:
            t, rel = t.get_array_element_type().get_canonical(), rel + ("[]",)
        if untyped and rel[-1] == "[]":
            found.append(rel)
        elif t.kind == TK.RECORD:
            found += [rel + r for r in _within(t, inner, depth + 1)]
        elif _plain(t) == _plain(inner):
            found.append(rel)
    return found


def _plain(t) -> str:
    return " ".join(w for w in t.spelling.split() if w not in ("const", "volatile", "restrict"))


def _function_type(callee):
    if callee is None:
        return None
    t = callee.type.get_canonical()
    if t.kind in (TK.POINTER, TK.BLOCKPOINTER):
        t = t.get_pointee().get_canonical()
    return t if t.kind in (TK.FUNCTIONPROTO, TK.FUNCTIONNOPROTO) else None


def _arithmetic(c) -> bool:
    if c.kind == CK.BINARY_OPERATOR:
        return c.binary_operator in (BO.Add, BO.Sub)
    if c.kind == CK.COMPOUND_ASSIGNMENT_OPERATOR:
        return c.binary_operator in (BO.AddAssign, BO.SubAssign)
    return c.kind == CK.UNARY_OPERATOR and _unary(c) in (POST_INC, POST_DEC, PRE_INC, PRE_DEC)


def _conversion(to, frm) -> str | None:
    """A narrowing or sign-changing integer conversion, described; None otherwise."""
    a, b = to.get_canonical(), frm.get_canonical()
    if a.kind not in SIGNED | UNSIGNED or b.kind not in SIGNED | UNSIGNED:
        return None
    to_size, from_size = a.get_size(), b.get_size()
    if to_size < from_size:
        return f"narrowing {frm.spelling} to {to.spelling}"
    if (a.kind in SIGNED) != (b.kind in SIGNED) and not (a.kind in SIGNED and to_size > from_size):
        return f"sign change {frm.spelling} to {to.spelling}"
    return None


def _signature(ftype) -> tuple:
    """(result, parameter types, variadic) with canonical spellings, for indirect calls."""
    if ftype is None or ftype.kind not in (TK.FUNCTIONPROTO, TK.FUNCTIONNOPROTO):
        return ("", (), True)
    params = tuple(t.get_canonical().spelling for t in ftype.argument_types()) \
        if ftype.kind == TK.FUNCTIONPROTO else ()
    variadic = ftype.kind == TK.FUNCTIONNOPROTO or ftype.is_function_variadic()
    return (ftype.get_result().get_canonical().spelling, params, variadic)


def _written_name(c, source) -> str:
    start = c.extent.start
    if start.file is None:
        return ""
    text = source(start.file.name)
    end = start.offset
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return text[start.offset:end]


def _skip_quoted(text, i) -> int:
    quote, i = text[i], i + 1
    while i < len(text) and text[i] != quote:
        i += 2 if text[i] == "\\" else 1
    return i


def _pack(rows, width) -> tuple:
    """Rows of `width`-tuples (or ints) as (index, flat) arrays: row i is flat[index[i]:index[i+1]]."""
    index, flat = array("i", [0]), array("i")
    for row in rows:
        for item in row:
            if width == 1:
                flat.append(item)
            else:
                flat.extend(item)
        index.append(index[-1] + len(row))
    return index, flat


def control_dependences(succ, kinds, exit_) -> list[tuple]:
    """Control dependences from the post-dominator tree (Ferrante, Ottenstein and Warren):
    per node, the (branching node, successor taken) pairs it depends on. `kinds` names each
    node's kind; code that cannot reach the exit leaves through its loop head."""
    n = len(succ)
    succ = [list(dict.fromkeys(s)) for s in succ]
    preds = [[] for _ in range(n)]
    for a, targets in enumerate(succ):
        for b in targets:
            preds[b].append(a)
    while True:  # an infinite loop leaves through its head, so post-dominance stays defined
        reach = set(_postorder(preds, exit_))
        stuck = [a for a in range(n) if a not in reach]
        if not stuck:
            break
        heads = [a for a in stuck if kinds[a] == "loop"]
        a = min(heads) if heads else max(stuck)
        succ[a].append(exit_)
        preds[exit_].append(a)
    ipdom = _idom(preds, succ, exit_)
    ipdom[exit_] = None
    control = [[] for _ in range(n)]
    for a in range(n):
        if len(succ[a]) < 2:
            continue
        stop = ipdom.get(a)
        for b in succ[a]:
            runner = b
            while runner is not None and runner != stop:
                control[runner].append((a, b))
                runner = ipdom.get(runner)
    return [tuple(dict.fromkeys(c)) for c in control]


def _postorder(succ, root) -> list[int]:
    order, seen, stack = [], {root}, [(root, iter(succ[root]))]
    while stack:
        v, it = stack[-1]
        for w in it:
            if w not in seen:
                seen.add(w)
                stack.append((w, iter(succ[w])))
                break
        else:
            stack.pop()
            order.append(v)
    return order


def _idom(nexts, prevs, root) -> dict:
    """Immediate dominators from `root` along `nexts` (Cooper, Harvey and Kennedy)."""
    order = _postorder(nexts, root)
    rank = {v: i for i, v in enumerate(order)}
    idom = {root: root}
    changed = True
    while changed:
        changed = False
        for v in reversed(order):
            if v == root:
                continue
            new = None
            for p in prevs[v]:
                if p not in idom:
                    continue
                if new is None:
                    new = p
                    continue
                a, b = p, new
                while a != b:
                    while rank[a] < rank[b]:
                        a = idom[a]
                    while rank[b] < rank[a]:
                        b = idom[b]
                new = a
            if new is not None and idom.get(v) != new:
                idom[v] = new
                changed = True
    return idom


def _coarse(rel):
    """A relative field path as summaries keep it: at most SUMMARY_SELECTORS selectors."""
    if rel is None or len(rel) <= SUMMARY_SELECTORS:
        return rel
    return rel[:SUMMARY_SELECTORS] + ("~",)


def _widen(path) -> tuple:
    """A path composed across calls, cut to MAX_SELECTORS selectors and "~" so that
    recursion through linked structures cannot grow summaries without bound."""
    return path if len(path) <= MAX_SELECTORS + 1 else path[:MAX_SELECTORS + 1] + ("~",)


def _wild(path) -> tuple:
    return path if path[-1] == "~" else path + ("~",)


def _strong(path) -> bool:
    return not any(s in ("*", "[]", "~") for s in path[1:]) and path[0] != "$mem"


def _overlap(use, d) -> bool:
    """Whether a definition of `d` may change what a use of `use` reads.

    A definition of a prefix covers everything below it; a use of a whole object reads its
    fields and array elements but not the memory its pointers point to, unless it ends in ~."""
    wild_use = use[-1] == "~"
    u = use[:-1] if wild_use else use
    e = d[:-1] if d[-1] == "~" else d
    if len(u) <= len(e):
        return e[:len(u)] == u and (wild_use or "*" not in e[len(u):])
    return u[:len(e)] == e


def _suffix(use, base):
    """The part of a use below `base`, or None when the use covers all of it."""
    stem = base[:-1] if base[-1] == "~" else base
    if len(use) <= len(stem) or (use[-1] == "~" and len(use) == len(stem) + 1):
        return None
    return use[len(stem):]


# ---- library models ------------------------------------------------------------------------

def _same(**entry):
    return entry


_COPY = _same(flows={"*0": ("*1", "2"), "ret": ("0",)},
              sinks={"2": "length", "0": "destination", "1": "source"})
_COMPARE = _same(flows={"ret": ("*0", "*1", "2")}, sinks={"2": "length", "0": "source", "1": "source"})
_SCAN = _same(flows={"ret": ("*0", "1", "2")}, sinks={"2": "length", "0": "source"})
_STRCMP = _same(flows={"ret": ("*0", "*1")}, sinks={"0": "string", "1": "string"})
_STRCHR = _same(flows={"ret": ("0", "*0", "1")}, sinks={"0": "string"})
_TO_NUMBER = _same(flows={"ret": ("*0",)}, sinks={"0": "string"})
_STRTO = _same(flows={"ret": ("*0", "2"), "*1": ("0",)}, sinks={"0": "string"})
_GETC = _same(flows={"ret": ("0",)}, sources=("ret",))
_READ = _same(flows={"*1": ("0", "2"), "ret": ("0", "2")}, sinks={"2": "length", "1": "destination"},
              sources=("*1", "ret"))
_VALUE = _same(flows={"ret": ("0",)})

# Functions whose bodies are not analyzed. Argument keys: "ret", "N" (argument N),
# "*N" (what argument N points to), "N+" and "*N+" (argument N and the ones after it).
# "flows" maps an output to the inputs it depends on; "sinks" names the role of an argument
# that decides a memory access; "sources" lists outputs read from outside the program.
# Callers extend the table by passing their own dict to `program`.
MODELS = {
    "memcpy": _COPY, "memmove": _COPY, "mempcpy": _COPY, "wmemcpy": _COPY, "wmemmove": _COPY,
    "memset": _same(flows={"*0": ("1", "2"), "ret": ("0",)}, sinks={"2": "length", "0": "destination"}),
    "wmemset": _same(flows={"*0": ("1", "2"), "ret": ("0",)}, sinks={"2": "length", "0": "destination"}),
    "bcopy": _same(flows={"*1": ("*0", "2")}, sinks={"2": "length", "1": "destination", "0": "source"}),
    "bzero": _same(flows={"*0": ("1",)}, sinks={"1": "length", "0": "destination"}),
    "explicit_bzero": _same(flows={"*0": ("1",)}, sinks={"1": "length", "0": "destination"}),
    "memcmp": _COMPARE, "bcmp": _COMPARE, "strncmp": _COMPARE, "strncasecmp": _COMPARE,
    "memchr": _SCAN, "memrchr": _SCAN,
    "strlen": _same(flows={"ret": ("*0",)}, sinks={"0": "string"}),
    "wcslen": _same(flows={"ret": ("*0",)}, sinks={"0": "string"}),
    "strnlen": _same(flows={"ret": ("*0", "1")}, sinks={"1": "length", "0": "source"}),
    "strcpy": _same(flows={"*0": ("*1",), "ret": ("0",)}, sinks={"0": "destination", "1": "string"}),
    "wcscpy": _same(flows={"*0": ("*1",), "ret": ("0",)}, sinks={"0": "destination", "1": "string"}),
    "stpcpy": _same(flows={"*0": ("*1",), "ret": ("0", "*1")}, sinks={"0": "destination", "1": "string"}),
    "strncpy": _COPY, "stpncpy": _COPY, "wcsncpy": _COPY,
    "strcat": _same(flows={"*0": ("*0", "*1"), "ret": ("0",)}, sinks={"0": "destination", "1": "string"}),
    "strncat": _same(flows={"*0": ("*0", "*1", "2"), "ret": ("0",)},
                     sinks={"2": "length", "0": "destination", "1": "source"}),
    "strlcpy": _same(flows={"*0": ("*1", "2"), "ret": ("*1",)},
                     sinks={"2": "length", "0": "destination", "1": "string"}),
    "strlcat": _same(flows={"*0": ("*0", "*1", "2"), "ret": ("*0", "*1")},
                     sinks={"2": "length", "0": "destination", "1": "string"}),
    "strcmp": _STRCMP, "strcasecmp": _STRCMP, "strcoll": _STRCMP,
    "strchr": _STRCHR, "strrchr": _STRCHR,
    "strstr": _same(flows={"ret": ("0", "*0", "*1")}, sinks={"0": "string", "1": "string"}),
    "strspn": _STRCMP, "strcspn": _STRCMP,
    "strdup": _same(flows={"ret": ("*0",)}, sinks={"0": "string"}),
    "strndup": _same(flows={"ret": ("*0", "1")}, sinks={"1": "length", "0": "source"}),
    "strtok": _same(flows={"ret": ("0", "*0", "*1"), "*0": ("*0", "*1")}, sinks={"1": "string"}),
    "atoi": _TO_NUMBER, "atol": _TO_NUMBER, "atoll": _TO_NUMBER, "atof": _TO_NUMBER,
    "strtol": _STRTO, "strtoul": _STRTO, "strtoll": _STRTO, "strtoull": _STRTO,
    "strtod": _STRTO, "strtof": _STRTO,
    "sprintf": _same(flows={"*0": ("*1", "2+", "*2+"), "ret": ("*1", "2+", "*2+")},
                     sinks={"0": "destination", "1": "format"}),
    "vsprintf": _same(flows={"*0": ("*1", "2", "*2"), "ret": ("*1", "2", "*2")},
                      sinks={"0": "destination", "1": "format"}),
    "snprintf": _same(flows={"*0": ("1", "*2", "3+", "*3+"), "ret": ("*2", "3+", "*3+")},
                      sinks={"1": "length", "0": "destination", "2": "format"}),
    "vsnprintf": _same(flows={"*0": ("1", "*2", "3", "*3"), "ret": ("*2", "3", "*3")},
                       sinks={"1": "length", "0": "destination", "2": "format"}),
    "__sprintf_chk": _same(flows={"*0": ("*3", "4+", "*4+"), "ret": ("*3", "4+", "*4+")},
                           sinks={"0": "destination", "3": "format"}),
    "__vsprintf_chk": _same(flows={"*0": ("*3", "4", "*4"), "ret": ("*3", "4", "*4")},
                            sinks={"0": "destination", "3": "format"}),
    "__snprintf_chk": _same(flows={"*0": ("1", "*4", "5+", "*5+"), "ret": ("*4", "5+", "*5+")},
                            sinks={"1": "length", "0": "destination", "4": "format"}),
    "__vsnprintf_chk": _same(flows={"*0": ("1", "*4", "5", "*5"), "ret": ("*4", "5", "*5")},
                             sinks={"1": "length", "0": "destination", "4": "format"}),
    "printf": _same(sinks={"0": "format"}), "vprintf": _same(sinks={"0": "format"}),
    "fprintf": _same(sinks={"1": "format"}), "vfprintf": _same(sinks={"1": "format"}),
    "dprintf": _same(sinks={"1": "format"}), "syslog": _same(sinks={"1": "format"}),
    "__printf_chk": _same(sinks={"1": "format"}), "__fprintf_chk": _same(sinks={"2": "format"}),
    "sscanf": _same(flows={"*2+": ("*0", "*1"), "ret": ("*0", "*1")}, sinks={"1": "format"}),
    "scanf": _same(sinks={"0": "format"}, sources=("*1+", "ret")),
    "fscanf": _same(sinks={"1": "format"}, sources=("*2+", "ret")),
    "read": _READ, "pread": _READ, "recv": _READ, "recvfrom": _READ,
    "fread": _same(flows={"*0": ("1", "2", "3"), "ret": ("1", "2", "3")},
                   sinks={"1": "size", "2": "length", "0": "destination"}, sources=("*0", "ret")),
    "fgets": _same(flows={"*0": ("1", "2"), "ret": ("0",)}, sinks={"1": "length", "0": "destination"},
                   sources=("*0",)),
    "gets": _same(sinks={"0": "destination"}, sources=("*0",)),
    "getc": _GETC, "fgetc": _GETC, "getchar": _GETC, "_IO_getc": _GETC, "getc_unlocked": _GETC,
    "getline": _same(flows={"*0": ("2",), "*1": ("2",), "ret": ("2",)}, sources=("*0", "*1", "ret")),
    "getdelim": _same(flows={"*0": ("3",), "*1": ("3",), "ret": ("3",)}, sources=("*0", "*1", "ret")),
    "getenv": _same(flows={"ret": ("*0",)}, sources=("ret",)),
    "malloc": _same(flows={"ret": ("0",)}, sinks={"0": "allocation size"}),
    "calloc": _same(flows={"ret": ("0", "1")}, sinks={"0": "allocation size", "1": "allocation size"}),
    "realloc": _same(flows={"ret": ("0", "*0", "1")}, sinks={"1": "allocation size"}),
    "reallocarray": _same(flows={"ret": ("0", "*0", "1", "2")},
                          sinks={"1": "allocation size", "2": "allocation size"}),
    "alloca": _same(flows={"ret": ("0",)}, sinks={"0": "allocation size"}),
    "aligned_alloc": _same(flows={"ret": ("0", "1")}, sinks={"1": "allocation size"}),
    "memalign": _same(flows={"ret": ("0", "1")}, sinks={"1": "allocation size"}),
    "posix_memalign": _same(flows={"*0": ("1", "2")}, sinks={"2": "allocation size"}),
    "free": _same(),
    "ntohl": _VALUE, "ntohs": _VALUE, "htonl": _VALUE, "htons": _VALUE,
    "abs": _VALUE, "labs": _VALUE, "llabs": _VALUE,
}
MEMORY_SINKS = {"subscript", "dereference of pointer arithmetic", "array new size",
                "variable-length array size"}


def _keys(spec: str, nargs: int) -> list[tuple]:
    """Port keys for a model argument key at a call with `nargs` arguments."""
    if spec == "ret":
        return [("ret",)]
    pointee = spec.startswith("*")
    number = spec.lstrip("*")
    first = int(number.rstrip("+"))
    indexes = range(first, nargs) if number.endswith("+") else [first] if first < nargs else []
    return [("arg*" if pointee else "arg", i) for i in indexes]


# ---- program: every function in every configuration ---------------------------------------

@dataclass(frozen=True)
class Target:
    """How one call resolves in one configuration."""
    kind: str                   # direct | indirect (by signature, uncertain) | model | external | unresolved
    functions: tuple[str, ...]  # Function.id for direct and indirect calls
    model: str | None
    name: str

    @property
    def summarized(self) -> bool:
        """Whether summaries cross this call through its callees' summaries."""
        return self.kind == "direct" or (self.kind == "indirect" and len(self.functions) <= MAX_CANDIDATES)


@dataclass(frozen=True)
class Summary:
    """What a function's outputs and sinks depend on, over all its configurations.

    Entry keys are ("arg", i), ("arg*", i) for what argument i points to (-1 is `this`),
    ("global", base), and ("varargs",). Output keys add ("ret",). A relative path narrows
    a key to fields below it; None means all of it."""
    outs: dict      # output key -> {relative path: frozenset of (entry key, relative path)}
    data: dict      # the same through data dependences only
    mods: frozenset  # globals this function or its callees may write
    reach: frozenset  # entry keys whose data reaches a memory sink here or in a callee
    sinks: dict     # (path, line, column, kind) of a sink here -> entry keys it depends on
    halts: frozenset = frozenset()  # entries that decide whether it returns (a check that aborts)


class _Facts(NamedTuple):
    """A summary as the fixpoint keeps it: each entry once, with a bit for data-only."""
    table: tuple     # ((output key, ((relative path, entries, data-only bits), ...)), ...)
    mods: frozenset
    reach: frozenset
    halts: frozenset  # entries deciding whether the function returns


class Node(NamedTuple):
    kind: str
    file: int     # index into the body's files
    line: int
    end_line: int
    context: int  # index into the body's enclosing-branch lines


class CallFacts(NamedTuple):
    node: int
    usr: str | None       # the declared callee; None for an indirect call
    name: str
    written: str          # the text at the call, for reports
    args: tuple           # per argument: (points to named memory, to const, constant)
    signature: tuple | None  # of an indirect call's function pointer
    flags: tuple          # "virtual", "noreturn"
    ins: dict             # input key -> slot
    outs: dict            # output key -> slot
    extent: tuple         # (line, column, end line, end column, start offset, end offset)


class _Rows:
    """Row i of a packed (index, flat) table as a list of `width`-tuples (or ints for 1)."""
    __slots__ = ("index", "flat", "width")

    def __init__(self, packed, width):
        self.index, self.flat = packed
        self.width = width

    def __len__(self):
        return len(self.index) - 1

    def __getitem__(self, i):
        w = self.width
        values = self.flat[self.index[i] * w:self.index[i + 1] * w]
        if w == 1:
            return values.tolist()
        return list(zip(*(values[k::w] for k in range(w))))

    def __iter__(self):
        return (self[i] for i in range(len(self)))


class _Nodes:
    __slots__ = ("kinds", "spans", "context")

    def __init__(self, ir):
        self.kinds, self.spans, self.context = ir["kinds"], ir["spans"], ir["context"]

    def __len__(self):
        return len(self.kinds)

    def __getitem__(self, n):
        s = self.spans
        return Node(NODE_KINDS[self.kinds[n]], s[3 * n], s[3 * n + 1], s[3 * n + 2], self.context[n])

    def __iter__(self):
        return (self[n] for n in range(len(self)))


class _Slots:
    """Slot -> its node (`node`) or its port tuple (`port`, None for a node's own slot)."""
    __slots__ = ("n_nodes", "table", "nodes", "refs", "port")

    def __init__(self, n_nodes, ports, port):
        self.n_nodes, (self.table, self.nodes, self.refs), self.port = n_nodes, ports, port

    def __len__(self):
        return self.n_nodes + len(self.refs)

    def __getitem__(self, s):
        if s < self.n_nodes:
            return None if self.port else s
        return self.table[self.refs[s - self.n_nodes]] if self.port else self.nodes[s - self.n_nodes]

    def __iter__(self):
        return (self[s] for s in range(len(self)))


class _Variant:
    """One configuration-specific body of a function, with views over its packed rows."""

    def __init__(self, index: int, body: Body):
        ir = body.ir
        self.index, self.function, self.configs, self.ir = index, body.function, body.configs, ir
        self.nodes, self.paths = _Nodes(ir), ir["paths"]
        self.deps, self.control, self.succ = _Rows(ir["deps"], 3), _Rows(ir["control"], 2), _Rows(ir["succ"], 1)
        self.calls = [CallFacts(*c[:7], dict(c[7]), dict(c[8]), c[9]) for c in ir["calls"]]
        self.written = set(ir["written"])
        self.n_nodes = len(self.nodes)
        self.exit = self.n_nodes - 1
        self.slot_node = _Slots(self.n_nodes, ir["ports"], False)
        self.slot_port = _Slots(self.n_nodes, ir["ports"], True)
        self.fin, self.fout = {}, defaultdict(list)
        table, _, refs = ir["ports"]
        for j, ref in enumerate(refs):
            port = table[ref]
            if port[0] == "fin":
                self.fin[port[1]] = self.n_nodes + j
            elif port[0] == "fout":
                self.fout[port[1]].append((port[2], self.n_nodes + j))
        self.ops = ir["ops"]
        self.call_at = {call.node: i for i, call in enumerate(self.calls)}
        self.ends = {call.node for call in self.calls if "noreturn" in call.flags}  # calls that end a path
        self.cut = set()            # calls to functions inferred never to return
        self.halting = frozenset()  # calls whose callee may not return, depending on arguments
        self._rdeps = self._controlled = None

    def call_port(self, slot, kind):
        """(call, key) of an "in" or "out" port slot, or None."""
        port = self.slot_port[slot]
        if port is None or port[0] != kind:
            return None
        return self.call_at[self.slot_node[slot]], port[1]

    def controlled(self) -> dict:
        """Branching node -> [(dependent node, successor taken)]."""
        if self._controlled is None:
            self._controlled = defaultdict(list)
            for n, controls in enumerate(self.control):
                for m, branch in controls:
                    self._controlled[m].append((n, branch))
        return self._controlled

    def rdeps(self):
        if self._rdeps is None:
            self._rdeps = defaultdict(list)
            for s, deps in enumerate(self.deps):
                for t, ui, di in deps:
                    self._rdeps[t].append((s, ui, di))
        return self._rdeps


def _digest(ir) -> bytes:
    """A body's lowering without its USRs: one function seen from two files or configurations
    often lowers alike."""
    plain = {k: [c[:1] + c[2:] for c in ir[k]] if k == "calls" else ir[k] for k in sorted(ir) if k != "usr"}
    return hashlib.sha256(pickle.dumps(plain)).digest()


def program(scan: Scan, root, models: dict = MODELS) -> "Program":
    """Resolve calls and compute summaries for every function body a scan lowered."""
    return Program(scan, root, models)


class Program:
    def __init__(self, scan: Scan, root, models: dict):
        self.root = Path(root)
        self.functions: dict[str, Function] = {f.id: f for f in scan.functions}
        self.models = models
        self.variants = [_Variant(i, b) for i, b in enumerate(b for b in scan.bodies
                                                               if b.function in self.functions)]
        self.of = defaultdict(list)
        usr = defaultdict(set)
        for v in self.variants:
            self.of[v.function].append(v)
            usr[v.ir["usr"]].add(v.function)
        self.signatures = {f: vs[0].ir["signature"] for f, vs in self.of.items()}
        self.all_signatures = {f: {_normal(v.ir["signature"]) for v in vs} for f, vs in self.of.items()}
        self.globals = {}  # base -> (name, path, first line, last line) of its definition
        self.writers, self.readers = defaultdict(list), defaultdict(list)  # global -> (variant, slot)
        for v in self.variants:
            self.globals.update(v.ir["globals"])
            for key, items in v.fout.items():
                if key[0] == "global":
                    self.writers[key[1]] += [(v.index, slot) for _, slot in items]
            for key, slot in v.fin.items():
                if key[0] == "global":
                    self.readers[key[1]].append((v.index, slot))
        addressed = set(scan.addressed) | {u for v in self.variants for u in v.ir["addressed"]}
        candidates = sorted({f for u in addressed for f in usr.get(u, ())})
        by_signature = {}  # one resolution per distinct signature of an indirect call
        interned = {}      # equal targets once
        self.targets: dict[tuple[int, int], Target] = {}
        self.callers = defaultdict(list)
        graph = {f: set() for f in self.of}
        for v in self.variants:
            for i, call in enumerate(v.calls):
                target = self._resolve(call, usr, candidates, by_signature)
                target = interned.setdefault(target, target)
                self.targets[(v.index, i)] = target
                for f in target.functions:
                    self.callers[f].append((v.index, i))
                    if target.summarized:
                        graph[v.function].add(f)
        self.noreturn = self._infer_noreturn()  # functions found never to return
        # Bodies equal but for USRs, with equal call targets, have equal summaries and slices:
        # summaries read one of them and traversals visit it for all, with all their configurations.
        self.distinct = {}  # function -> its variants with distinct bodies
        self.rep = list(range(len(self.variants)))  # variant -> the equal variant traversals visit
        for f, vs in self.of.items():
            kept = {}
            for v in vs:
                key = (_digest(v.ir), tuple(self.targets[(v.index, c)] for c in range(len(v.calls)))) \
                    if len(vs) > 1 else None
                self.rep[v.index] = kept.setdefault(key, v).index
            self.distinct[f] = list(kept.values())
        configs = defaultdict(set)
        for v in self.variants:
            configs[self.rep[v.index]].update(v.configs)
        self.configs_of = {r: tuple(sorted(c)) for r, c in configs.items()}  # representative -> configurations
        calls_of = defaultdict(set)  # every call edge, also those summaries do not cross
        for (vi, c), target in self.targets.items():
            calls_of[self.variants[vi].function].update(target.functions)
        self.mods = {}  # globals a function or anything it may call writes
        for component in _components({f: sorted(calls_of[f]) for f in self.of}):
            found = set()
            for f in component:
                for v in self.of[f]:
                    found.update(v.ir["modified"])
                found.update(g for callee in calls_of[f] if callee not in component
                             for g in self.mods.get(callee, ()))
            for f in component:
                self.mods[f] = frozenset(found)
        self.partners = defaultdict(lambda: defaultdict(set))  # callee -> j -> i: one object for both
        for v in self.variants:
            for c, call in enumerate(v.calls):
                for flag in call.flags:
                    if flag.startswith("same object:"):
                        _, i, j = flag.split(":")
                        for f in self.targets[(v.index, c)].functions:
                            self.partners[f][int(i)].add(int(j))
                            self.partners[f][int(j)].add(int(i))
        self._summaries: dict[str, _Facts] = {}
        self.bounded: set[str] = set()   # functions whose summaries hit MAX_ROUNDS
        self.rounds = 0                  # summaries computed
        self._open = set()               # functions whose summaries may still change
        self._stable, self._volatile = {}, {}  # per-call caches over final / open callees
        self._in_index, self._indexed = {}, 0  # see _narrow
        for component in _components({f: sorted(c) for f, c in graph.items()}):
            self._open = set(component)
            members = set(component)
            inside = {f: [g for g in component if f in graph[g]] for f in component}
            order = []  # callees before callers as far as the cycles allow
            for root in component:
                if root not in order:
                    order += [f for f in _postorder({f: sorted(graph[f] & members) for f in members}, root)
                              if f not in order]
            work, queued, budget = deque(order), set(order), MAX_ROUNDS * len(component)
            while work:  # a recursive component is iterated only where a callee changed
                f = work.popleft()
                queued.discard(f)
                budget -= 1
                if budget < 0:
                    self.bounded.update(component)
                    break
                self.rounds += 1
                s = self._summarize(f)
                if s != self._summaries.get(f):
                    self._summaries[f] = s
                    self._volatile.clear()
                    for g in inside[f]:
                        if g not in queued:
                            work.append(g)
                            queued.add(g)
            if component[0] in self.bounded:
                # incomplete summaries would hide writes from callers: calls into the
                # component become unknown callees, and its members are summarized once more
                self._volatile.clear()
                for f in component:
                    self.rounds += 1
                    self._summaries[f] = self._summarize(f)
            self._open = set()
            self._volatile.clear()
        callers_of = defaultdict(set)
        for f, callees in calls_of.items():
            for g in callees:
                callers_of[g].add(f)
        self.reaches_bound = set(self.bounded)  # functions whose calls lead into a bounded component
        stack = list(self.bounded)
        while stack:
            for f in callers_of[stack.pop()]:
                if f not in self.reaches_bound:
                    self.reaches_bound.add(f)
                    stack.append(f)
        self._edge_cache, self._widens = {}, {}

    # -- calls ----------------------------------------------------------------------------

    def _resolve(self, call, usr, candidates, by_signature) -> Target:
        _, callee, name, written, *_ = call
        if callee is not None:
            functions = tuple(sorted(usr.get(callee, ())))
            if functions:
                return Target("direct", functions, None, name)
            model = self.model(name)  # the declaration's name; the text at a macro is not the callee
            return Target("model" if model else "external", (), model, name or written)
        signature, nargs = call.signature, len(call.args)
        functions = by_signature.get((signature, nargs))
        if functions is None:
            normal = _normal(signature) if signature is not None else None
            functions = by_signature[(signature, nargs)] = tuple(
                f for f in candidates if any(_compatible(s, normal, nargs) for s in self.all_signatures[f]))
        return Target("indirect" if functions else "unresolved", functions, None, written)

    def _summarized(self, v, c) -> bool:
        """Whether summaries cross call `c` through its callees' summaries."""
        target = self.targets[(v.index, c)]
        return target.summarized and not (self.bounded and any(f in self.bounded for f in target.functions))

    def _infer_noreturn(self) -> set:
        """Functions none of whose paths return, because each ends in a call that does not
        (an attribute, a known name, or a function inferred so). Control dependences are
        recomputed where such a call now ends a path, so the guard before it governs what follows."""
        inferred = set()

        def stops(v, c):
            call = v.calls[c]
            target = self.targets[(v.index, c)]
            return "noreturn" in call.flags or (target.kind == "direct" and all(f in inferred for f in target.functions))

        def returns(v):
            seen, stack = {0}, [0]
            while stack:
                n = stack.pop()
                if n == v.exit:
                    return True
                c = v.call_at.get(n)
                if c is not None and stops(v, c):
                    continue
                for m in v.succ[n]:
                    if m not in seen:
                        seen.add(m)
                        stack.append(m)
            return False

        check = {v.function for v in self.variants if v.ends or not any(v.exit in s for s in v.succ)}
        while check:
            found = {f for f in sorted(check) if f not in inferred and not any(returns(v) for v in self.of[f])}
            inferred |= found
            check = {self.variants[cv].function for f in found for cv, _ in self.callers.get(f, ())}
        for v in self.variants:
            cut = [c for c in range(len(v.calls)) if "noreturn" not in v.calls[c].flags and stops(v, c)]
            if cut:
                v.cut = {v.calls[c].node for c in cut}
                v.ends.update(v.cut)
                self._recontrol(v, v.halting, force=True)
        return inferred

    def _recontrol(self, v, halting, force=False):
        """Control dependences with calls that never return ending their path and calls that
        may not return (depending on arguments) branching to the exit as well."""
        if halting == v.halting and not force:
            return
        succ = [list(s) for s in v.succ]
        for n in v.cut:
            succ[n] = [v.exit]
        for n in halting - v.cut:
            succ[n].append(v.exit)
        v.control = control_dependences(succ, [node.kind for node in v.nodes], v.exit)
        v.halting, v._controlled = halting, None

    def _halts(self, v, c) -> frozenset:
        """Callee entries that decide whether call `c` returns, mapped to this call."""
        def compute():
            found = {}
            for f in self.targets[(v.index, c)].functions if self._summarized(v, c) else ():
                s = self._summaries.get(f)
                for entry in sorted(s.halts, key=repr) if s is not None else ():
                    found.update((w, None) for w, _ in self._into(v, c, f, entry, "h"))
            return tuple(found)
        return self._cached("halts", v, c, compute)

    def model(self, name: str) -> str | None:
        return model_name(name, self.models)

    def _cached(self, name, v, c, compute):
        """A fact about call `c` derived from its callees' summaries: kept for good once
        every callee's summary is final, recomputed while one may still change."""
        key = (name, v.index, c)
        found = self._stable.get(key)
        if found is None:
            found = self._volatile.get(key)
        if found is None:
            found = compute()
            open_ = any(f in self._open for f in self.targets[(v.index, c)].functions)
            cache = self._volatile if open_ else self._stable
            if len(cache) > CALL_CACHE:
                cache.clear()
            cache[key] = found
        return found

    def _mods(self, v, c) -> frozenset:
        """Globals call `c` may write: from every target, summarized or not."""
        def compute():
            return frozenset().union(*(self.mods.get(f, ()) for f in self.targets[(v.index, c)].functions))
        return self._cached("mods", v, c, compute)

    def _table(self, v, c, data_only) -> dict:
        """Output key -> [(relative path, caller vertices with edge kinds)] over every callee
        of a call that summaries cross, with callee entries already mapped to this call."""
        def compute():
            merged = defaultdict(lambda: defaultdict(dict))
            target = self.targets[(v.index, c)]
            kind = "s" if target.kind == "direct" else "u"
            for f in target.functions if self._summarized(v, c) else ():
                s = self._summaries.get(f)
                if s is not None:
                    for key, rels in s.table:
                        for rel, entries, mask in rels:
                            found = merged[key][rel]
                            for i, entry in enumerate(entries):  # sorted, not hash order
                                if data_only and not mask >> i & 1:
                                    continue
                                for w in self._into(v, c, f, entry, kind):
                                    found[w] = None
            return {key: [(rel, tuple(found)) for rel, found in rels.items()] for key, rels in merged.items()}
        return self._cached("data" if data_only else "outs", v, c, compute)

    def _into(self, v, c, f, entry, kind):
        """Caller vertices at call `c` for a callee entry (key, relative path)."""
        key, rel = entry
        ins = v.calls[c].ins
        if key == ("varargs",):
            fixed = len(self.signatures[f][1])
            return [(("in", c, k, None), kind) for k in ins if k[0] in ("arg", "arg*") and k[1] >= fixed]
        if key in ins:
            return [(("in", c, key, rel), kind)]
        if key[0] == "global":
            return [(("vg", v.calls[c].node, key[1]), kind)]
        return []

    # -- dependence graph -----------------------------------------------------------------

    def edges(self, v, x, data_only=False):
        """Backward edges of vertex `x` in variant `v`: [(vertex, kind)].

        Vertices are slot numbers and tuples: ("in"/"out", call, key, relative path) for
        call ports narrowed to fields, ("fin", key, relative path) for function entry,
        ("vg", node, global) for the value of a global this body never assigns, read at
        `node`, and ("gnode", global) for every write of a global anywhere: across functions
        globals are flow-insensitive. Kinds: d data, c control, s callee summary,
        u uncertain indirect call, m library model, x external callee without model,
        g global written elsewhere."""
        if type(x) is int or x[0] == "in":
            out, writes = [], {}  # many dependences wait on one call output
            for w, check in self._local(v, x):
                if check is not None:
                    found = writes.get(check)
                    if found is None:
                        found = writes[check] = self._writes(v, *check)
                    if not found:
                        continue
                out.append((w, "d"))
            if not data_only:
                n = v.slot_node[x] if type(x) is int else None
                out += ([(m, "c") for m in dict.fromkeys(m for m, _ in v.control[n])] if n is not None
                        else [(v.calls[x[1]].node, "c")])
                if n is not None and x == n and n in v.halting:  # what decides whether it returns
                    out += [(w, "h") for w in self._halts(v, v.call_at[n])]
            return out
        tag = x[0]
        out = []
        if tag == "fin" and x[1][0] == "arg*" and self.partners.get(v.function):
            # a caller passes one object for two pointer parameters: writes through either
            for i in sorted(self.partners[v.function].get(x[1][1], ())):
                out += [(slot, "d") for _, slot in v.fout.get(("arg*", i), ())]
        if tag == "out":
            _, c, key, suffix = x
            out += self._through(v, c, key, suffix, data_only)
            if not data_only:
                out.append((v.calls[c].node, "c"))
        elif tag == "vg":
            out += [(("fin", ("global", x[2]), None), "d"), (("gnode", x[2]), "g")]
        return out

    def _local(self, v, x) -> list:
        """Data dependences of a slot or call input as (vertex, check). `check` is the
        (call, key, suffix) whose callees must write for the edge to exist. Keeping these
        between rounds made a recursive component hold its whole graph (3 GB on lua)."""
        found = []
        if type(x) is int:
            for t, ui, di in v.deps[x]:  # a dependence on another node's own slot needs no lookup
                found.append((t, None) if ui < 0 else self._target(v, x, t, v.paths[ui], di))
        else:
            _, c, key, rel = x
            slot = v.calls[c].ins.get(key)
            deps = v.deps[slot] if slot is not None else ()
            if rel is not None and len(deps) >= INDEXED:
                deps = self._narrow(v, slot, deps, rel)
            narrowed = {}  # use path -> the part of it this input reads
            for t, ui, di in deps:
                u = narrowed.get(ui)
                if u is None:
                    u = v.paths[ui]
                    if rel is not None:
                        u = _widen((u[:-1] if u[-1] == "~" else u) + rel)
                    narrowed[ui] = u
                if rel is not None and not _overlap(u, v.paths[di]):
                    continue
                found.append(self._target(v, slot, t, u, di))
        return found

    def _narrow(self, v, slot, deps, rel) -> list:
        """The dependences of input `slot` that may overlap its part `rel`, in their order:
        a definition that continues past the use with another selector than `rel` cannot.
        Inputs a pointer to a large struct passes otherwise scanned every definition of the
        struct once for each field a callee reads (lua: 2 million per slice level)."""
        key = (v.index, slot)
        index = self._in_index.get(key)
        if index is None:
            index = defaultdict(lambda: array("i"))  # (use, next selector or None) -> positions
            for i, (_, ui, di) in enumerate(deps):
                u, d = v.paths[ui], v.paths[di]
                n = len(u) - (u[-1] == "~")
                e = d[:-1] if d[-1] == "~" else d
                index[(ui, e[n] if len(e) > n else None)].append(i)
            if self._indexed > INDEX_CACHE:
                self._in_index.clear()
                self._indexed = 0
            self._in_index[key] = index = dict(index)
            self._indexed += len(deps)
        positions = []
        for ui in dict.fromkeys(ui for ui, _ in index):
            u = v.paths[ui]
            stem = u[:-1] if u[-1] == "~" else u
            narrowed = _widen(stem + rel)
            if len(narrowed) - (narrowed[-1] == "~") > len(stem):
                positions += index.get((ui, narrowed[len(stem)]), ())
                positions += index.get((ui, None), ())
            else:
                positions += [i for (w, _), found in index.items() if w == ui for i in found]
        return [deps[i] for i in sorted(positions)]

    def _target(self, v, use_slot, t, u, di):
        """(vertex, check) a data dependence on slot `t` leads to: `check` names the call
        output whose callees must write what the use reads."""
        port = v.slot_port[t]
        if port is None or port[0] not in ("out", "fin"):
            return t, None
        d = v.paths[di]
        if port[0] == "out":
            c, key = v.call_at[v.slot_node[t]], port[1]
            suffix = None if key == ("ret",) else _coarse(_suffix(u, d))
            return ("out", c, key, suffix), (c, key, suffix)
        key = port[1]
        if key[0] == "global" and key[1] not in v.written:
            return ("vg", v.slot_node[use_slot], key[1]), None
        return ("fin", key, _coarse(_suffix(u, d)) if key[0] in ("arg*", "global") else None), None

    def _writes(self, v, c, key, suffix) -> bool:
        if key == ("ret",):
            return True
        return self._cached(("writes", key, suffix), v, c, lambda: self._writes_now(v, c, key, suffix))

    def _writes_now(self, v, c, key, suffix) -> bool:
        if key[0] == "escaped":  # a local whose address left the function earlier
            return True
        target = self.targets[(v.index, c)]
        call = v.calls[c]
        if key[0] == "global":  # a library does not write the program's globals
            return key[1] in self._mods(v, c) or (target.kind not in ("external", "model")
                                                  and not self._summarized(v, c))
        if self._summarized(v, c):
            return any(suffix is None or not rel or _overlap(("",) + suffix, ("",) + rel)
                       for rel, _ in self._table(v, c, False).get(key, ()))
        if target.kind == "model":  # outputs it computes, and outputs read from outside
            nargs = len(call.args)
            model = self.models[target.model]
            return any(key in _keys(spec, nargs) for spec in (*model.get("flows", {}), *model.get("sources", ())))
        return not (key[0] == "arg*" and 0 <= key[1] < len(call.args) and call.args[key[1]][1])

    def _through(self, v, c, key, suffix, data_only):
        target = self.targets[(v.index, c)]
        call = v.calls[c]
        out = []
        if key[0] == "global":
            return [(("gnode", key[1]), "g")]
        if key[0] == "escaped":
            return [(("in", c, k, None), "w") for k in call.ins]
        if self._summarized(v, c):
            for rel, found in self._table(v, c, data_only).get(key, ()):
                if suffix is None or not rel or _overlap(("",) + suffix, ("",) + rel):
                    out += found
            if target.kind == "indirect" and not data_only and ("fn",) in call.ins:
                out.append((("in", c, ("fn",), None), "u"))
        elif target.kind == "model":
            flows = self.models[target.model].get("flows", {})
            nargs = len(call.args)
            for spec, inputs in flows.items():
                if key in _keys(spec, nargs):
                    out += [(("in", c, k, None), "m") for i in inputs for k in _keys(i, nargs)
                            if k in call.ins]
        else:
            if key[0] == "arg*" and 0 <= key[1] < len(call.args) and call.args[key[1]][1]:
                return out  # an unknown callee does not write through a pointer to const
            kind = "u" if target.kind == "indirect" else "x"
            out += [(("in", c, k, None), kind) for k in call.ins]
        return out

    # -- summaries ------------------------------------------------------------------------

    def memory_sinks(self, v):
        """Vertices whose data decides a memory access in `v`, with (kind, detail, extent)."""
        found = []
        for slot, kind, detail, *extent in v.ops:
            if kind in MEMORY_SINKS:
                found.append(([slot], kind, detail, tuple(extent), v.slot_node[slot]))
        for c, call in enumerate(v.calls):
            target = self.targets[(v.index, c)]
            if target.kind != "model":
                continue
            roles = self.models[target.model].get("sinks", {})
            starts, described = [], []
            for spec, role in sorted(roles.items()):
                for key in _keys(spec, len(call.args)):
                    if key in call.ins and not (role == "format" and call.args[key[1]][2]):
                        starts.append(("in", c, key, None))
                        described.append(f"argument {key[1]} {role}")
            if starts:
                found.append((starts, "call", f"{target.model}: " + ", ".join(described),
                              tuple(call.extent), call.node))
        return found

    def callee_sinks(self, v) -> list:
        """Caller vertices whose data reaches a memory sink inside a callee."""
        found = []
        for c in range(len(v.calls)):
            def compute():
                vertices = {}
                for g in self.targets[(v.index, c)].functions:
                    s = self._summaries.get(g)
                    if s is not None:
                        for key in sorted(s.reach, key=repr):
                            vertices.update((w, None) for w, _ in self._into(v, c, g, (key, None), "s"))
                return tuple(vertices)
            found += self._cached("reach", v, c, compute)
        return found

    def feeding(self, v) -> set:
        """Vertices of `v` whose data reaches a memory access here or in a callee."""
        starts = [w for starts, *_ in self.memory_sinks(v) for w in starts] + self.callee_sinks(v)
        seen, stack = set(starts), list(starts)
        while stack:
            for w, _ in self.edges(v, stack.pop(), True):
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        return seen

    def _summarize(self, f) -> "_Facts":
        """Summarize from scratch over the current callee summaries."""
        outs, data = defaultdict(lambda: defaultdict(set)), defaultdict(lambda: defaultdict(set))
        reach, halts = set(), set()
        for v in self.of[f]:  # slices read every variant's control dependences
            self._recontrol(v, frozenset(v.calls[c].node for c in range(len(v.calls)) if self._halts(v, c)))
        for v in self.distinct[f]:
            known = {}  # edges of a vertex, shared by the passes below

            def every(x):
                found = known.get(x)
                if found is None:
                    found = known[x] = self.edges(v, x)
                return [w for w, _ in found]

            def data_only(x):  # without control edges; a call output reads the data-only table
                if type(x) is tuple and x[0] == "out":
                    return [w for w, _ in self.edges(v, x, True)]
                found = known.get(x)
                if found is None:
                    found = known[x] = self.edges(v, x)
                return [w for w, kind in found if kind != "c"]

            roots = [slot for items in v.fout.values() for _, slot in items]
            for succ, table in ((every, outs), (data_only, data)):
                found = _reach(roots, succ)
                for key, items in v.fout.items():
                    for rel, slot in items:
                        table[key][_coarse(rel)] |= _entries(found[slot])
            starts = [w for vertices, *_ in self.memory_sinks(v) for w in vertices] + self.callee_sinks(v)
            seen, stack = set(starts), list(starts)
            while stack:  # entries whose data reaches a memory sink
                x = stack.pop()
                if type(x) is tuple and x[0] == "fin":
                    reach.add(x[1])
                for w in data_only(x):
                    if w not in seen:
                        seen.add(w)
                        stack.append(w)
            ends = sorted(v.ends | v.halting)
            seen, stack = set(ends), list(ends)
            while stack:  # entries deciding whether a path reaches a call that does not return
                x = stack.pop()
                if type(x) is tuple and x[0] == "fin":
                    halts.add((x[1], x[2]))
                for w in every(x):
                    if w not in seen:
                        seen.add(w)
                        stack.append(w)
        table = []
        for key in sorted(outs, key=repr):
            rels = []
            for rel in sorted(outs[key], key=repr):
                entries = tuple(sorted(outs[key][rel] | data[key][rel], key=repr))
                only = data[key][rel]
                rels.append((rel, entries, sum(1 << i for i, e in enumerate(entries) if e in only)))
            table.append((key, tuple(rels)))
        return _Facts(tuple(table), self.mods[f], frozenset(sorted(reach, key=repr)),
                      frozenset(sorted(halts, key=repr)))

    def widens(self, v, x) -> bool:
        """Whether reading call input `x` composes a field path past MAX_SELECTORS."""
        if type(x) is not tuple or x[0] != "in" or x[3] is None:
            return False
        key = (v.index, x)
        found = self._widens.get(key)
        if found is None:
            slot = v.calls[x[1]].ins.get(x[2])
            found = self._widens[key] = slot is not None and any(
                len((v.paths[ui][:-1] if v.paths[ui][-1] == "~" else v.paths[ui]) + x[3]) > MAX_SELECTORS + 1
                for _, ui, _ in v.deps[slot])
        return found

    def summary(self, function: str) -> Summary | None:
        """A function's summary, with the entries each of its own sinks depends on."""
        facts = self._summaries.get(function)
        if facts is None:
            return None
        sinks = defaultdict(set)
        for v in self.of[function]:
            local = self.memory_sinks(v)
            found = _reach([w for vertices, *_ in local for w in vertices],
                           lambda x: [w for w, _ in self.edges(v, x)])
            for vertices, kind, _, extent, node in local:
                where = (v.ir["files"][v.nodes[node].file], extent[0], extent[1], kind)
                for w in vertices:
                    sinks[where].update(key for key, _ in _entries(found[w]))
        outs = {key: {rel: frozenset(entries) for rel, entries, _ in rels} for key, rels in facts.table}
        data = {key: {rel: frozenset(e for i, e in enumerate(entries) if mask >> i & 1)
                      for rel, entries, mask in rels} for key, rels in facts.table}
        return Summary(outs, data, facts.mods, facts.reach,
                       {k: frozenset(e) for k, e in sorted(sinks.items())}, facts.halts)

    # -- traversals -----------------------------------------------------------------------

    def backward(self, starts, stop=None) -> dict:
        """Everything the starting vertices depend on, across calls in both directions.

        Paths that enter a callee from one caller and return to another are excluded as in
        Horwitz, Reps and Binkley's two phases, here as one breadth-first search over
        (vertex, may climb): climbing into callers is allowed until the path has descended
        into a callee. Distances are therefore exact. `stop(level, new)` is asked after each
        distance level with the vertices it added; when it returns True the search ends.
        Returns {(variant, vertex): (distance, edge kind, parent)}."""
        seen, climbing = {}, set()
        level_vertices = []
        for v, x in ((self.rep[v], x) for v, x in starts):
            if (v, x) not in seen:
                seen[(v, x)] = (0, "sink", None)
                climbing.add((v, x))
                level_vertices.append((v, x, True))
        level = 0
        while level_vertices:
            level += 1
            following, added = [], []
            for v, x, climb in level_vertices:
                for w, y, kind in self._backward_edges(v, x, climb):
                    still = climb and kind != "e"
                    key = (w, y)
                    if key not in seen:
                        seen[key] = (level, kind, (v, x))
                        added.append(key)
                    elif not (still and key not in climbing):
                        continue  # reached before, or only now without the right to climb
                    if still:
                        climbing.add(key)
                    following.append((w, y, still))
            level_vertices = following
            if stop is not None and level_vertices and stop(level, added):
                break
        return seen

    def _backward_edges(self, vi, x, climb):
        v = self.variants[vi]
        key = (vi, x)
        local = self._edge_cache.get(key)
        if local is None:
            if len(self._edge_cache) > EDGE_CACHE:
                self._edge_cache.clear()
            local = self._edge_cache[key] = self.edges(v, x)
        out = [(vi, w, kind) for w, kind in local]
        if type(x) is tuple:
            if climb and x[0] == "fin":
                for cv, c in self._callers(v.function):
                    caller = self.variants[cv]
                    out += [(cv, w, "a") for w, _ in self._into(caller, c, v.function, x[1:], "a")]
            elif climb and x[0] == "gnode":
                out += [(w, slot, "g") for w, slot in dict.fromkeys((self.rep[w], slot)
                                                                     for w, slot in self.writers.get(x[1], ()))]
            elif x[0] == "out":
                out += self._descend(v, x[1], x[2], x[3])
        return out

    def _callers(self, function):
        """Calls of `function` in the variants traversals visit."""
        return dict.fromkeys((self.rep[cv], c) for cv, c in self.callers.get(function, ()))

    def _descend(self, v, c, key, suffix):
        out = []
        for f in self.targets[(v.index, c)].functions:
            for w in self.distinct[f]:
                for rel, slot in w.fout.get(key, ()):
                    if suffix is None or not rel or _overlap(("",) + suffix, ("",) + rel):
                        out.append((w.index, slot, "e"))
        return out

    def forward(self, starts) -> dict:
        """Everything data from the starting vertices reaches, in the same two phases as
        `backward` with the directions reversed. Control dependences are not followed."""
        seen = {}
        queue = deque()
        for v, x in ((self.rep[v], x) for v, x in starts):
            if (v, x) not in seen:
                seen[(v, x)] = (0, "source", None)
                queue.append((v, x))
        for climb in (True, False):
            if not climb:
                queue = deque(sorted(seen, key=lambda k: seen[k][0]))
            while queue:
                v, x = queue.popleft()
                distance = seen[(v, x)][0] + 1
                for w, y, kind in self._forward_edges(v, x, climb):
                    if (w, y) not in seen:
                        seen[(w, y)] = (distance, kind, (v, x))
                        queue.append((w, y))
        return seen

    def _forward_edges(self, vi, x, climb):
        v = self.variants[vi]
        out = []
        if type(x) is int:
            slots = [x]
            port = v.slot_port[x]
            if climb and port is not None and port[0] == "fout":
                for cv, c in self._callers(v.function):
                    caller = self.variants[cv]
                    if port[1] in caller.calls[c].outs:
                        out.append((cv, ("out", c, port[1], None), "a"))
                if port[1][0] == "global":  # every function that reads it, flow-insensitively
                    out += [(w, ("fin", port[1], None), "g")
                            for w in dict.fromkeys(self.rep[w] for w, _ in self.readers.get(port[1][1], ()))]
        elif x[0] == "fin":
            slots = [v.fin[x[1]]] if x[1] in v.fin else []
        elif x[0] == "out":
            slots = [v.calls[x[1]].outs[x[2]]] if x[2] in v.calls[x[1]].outs else []
        elif x[0] == "in":
            slots = []
            out += self._forward_through(v, x[1], x[2], climb)
        else:
            slots = []
        rdeps = v.rdeps()
        for s in slots:
            for t, _, _ in rdeps.get(s, ()):
                port = v.call_port(t, "in")
                if port is not None:
                    c, key = port
                    out.append((vi, ("in", c, key, None), "d"))
                else:
                    out.append((vi, t, "d"))
        return out

    def _forward_through(self, v, c, key, climb):
        target = self.targets[(v.index, c)]
        call = v.calls[c]
        outs = call.outs
        out = []
        if target.kind in ("direct", "indirect"):
            kind = "s" if target.kind == "direct" else "u"
            summarized = self._summarized(v, c)
            out += [(v.index, ("out", c, k, None), "w") for k in outs if k[0] == "escaped"]
            if not summarized:
                out += [(v.index, ("out", c, k, None), kind) for k in outs
                        if not (k[0] == "arg*" and 0 <= k[1] < len(call.args) and call.args[k[1]][1])]
            for f in target.functions:
                s = self._summaries.get(f) if summarized else None
                fixed = len(self.signatures[f][1])
                callee_key = ("varargs",) if key[0] in ("arg", "arg*") and key[1] >= fixed and \
                    self.signatures[f][2] else key
                if s is not None:
                    for out_key, rels in s.table:
                        if out_key in outs and any(e[0] == callee_key and mask >> i & 1
                                                   for _, es, mask in rels for i, e in enumerate(es)):
                            out.append((v.index, ("out", c, out_key, None), kind))
                if not climb:
                    for w in self.distinct[f]:
                        if callee_key in w.fin:
                            out.append((w.index, ("fin", callee_key, None), "e"))
        elif target.kind == "model":
            flows = self.models[target.model].get("flows", {})
            nargs = len(call.args)
            for spec, inputs in flows.items():
                if any(key in _keys(i, nargs) for i in inputs):
                    out += [(v.index, ("out", c, k, None), "m") for k in _keys(spec, nargs) if k in outs]
        else:
            out += [(v.index, ("out", c, k, None), "x") for k in outs
                    if not (k[0] == "arg*" and 0 <= k[1] < len(call.args) and call.args[k[1]][1])]
        return out

    # -- source locations -----------------------------------------------------------------

    def node_of(self, vi, x) -> int | None:
        """The CFG node a vertex stands for, or None for a virtual vertex."""
        v = self.variants[vi]
        if type(x) is int:
            return v.slot_node[x]
        if x[0] in ("in", "out"):
            return v.calls[x[1]][0]
        if x[0] == "fin":
            return 0
        return None


def _entries(found) -> set:
    return {(x[1], x[2]) for x in found}


def _order(item):
    return repr(item)


def _bits(mask):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _is_entry(x) -> bool:
    return type(x) is tuple and x[0] == "fin"


def _reach(roots, succ, terminal=_is_entry) -> "_Reached":
    """For every vertex reachable from `roots`, the terminal vertices it reaches.

    Tarjan's SCCs with the reached terminals of each component as an integer bit set, so
    one pass answers every vertex at the cost of word operations."""
    index, low, bits = {}, {}, {}
    stack, on_stack, acc = [], set(), {}
    reached = _Reached(bits)
    counter = 0
    for root in roots:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        acc[root] = 0
        work = [(root, iter(succ(root)))]
        while work:
            v, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    acc[w] = 0
                    work.append((w, iter(succ(w))))
                    pushed = True
                    break
                if w in on_stack:
                    if index[w] < low[v]:
                        low[v] = index[w]
                else:
                    acc[v] |= bits[w]
            if pushed:
                continue
            work.pop()
            if low[v] == index[v]:
                members, total = [], 0
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    members.append(w)
                    total |= acc.pop(w)
                    if terminal(w):
                        total |= reached.bit(w)
                    if w == v:
                        break
                for w in members:
                    bits[w] = total
            if work:
                parent = work[-1][0]
                if v in bits:
                    acc[parent] |= bits[v]
                elif low[v] < low[parent]:
                    low[parent] = low[v]
    return reached


class _Reached:
    """Vertex -> frozenset of the terminals it reaches, decoded from bit sets on demand."""

    def __init__(self, bits):
        self.bits, self.terminals, self.numbers, self.decoded = bits, [], {}, {}

    def bit(self, terminal) -> int:
        number = self.numbers.get(terminal)
        if number is None:
            number = self.numbers[terminal] = len(self.terminals)
            self.terminals.append(terminal)
        return 1 << number

    def __getitem__(self, vertex) -> frozenset:
        mask = self.bits[vertex]
        found = self.decoded.get(mask)
        if found is None:
            found = self.decoded[mask] = frozenset(self.terminals[i] for i in _bits(mask))
        return found


def _components(graph: dict) -> list[list]:
    """Strongly connected components, callees before callers (Tarjan)."""
    found = []
    index, low, stack, on_stack = {}, {}, [], set()
    counter = 0
    for root in sorted(graph):
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(graph[root]))]
        while work:
            v, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(graph.get(w, ()))))
                    pushed = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if pushed:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == v:
                        break
                found.append(sorted(component))
    return found


def _compatible(function, call, nargs) -> bool:
    """Whether a function could be the target of an indirect call passing `nargs` arguments;
    both signatures `_normal`."""
    if call is None:
        return False
    result, params, variadic = function
    call_result, call_params, call_variadic = call
    if not _same_type(result, call_result):
        return False
    if call_variadic and not call_params:  # `int (*f)()` declares no parameters
        return len(params) == nargs or (variadic and len(params) <= nargs)
    if len(params) != len(call_params) or variadic != call_variadic:
        return False
    return all(_same_type(a, b) for a, b in zip(params, call_params))


def _normal(signature) -> tuple:
    def norm(t):
        for word in ("const", "volatile", "restrict", "__restrict"):
            t = t.replace(word + " ", "").replace(" " + word, "")
        return " ".join(t.split())
    result, params, variadic = signature
    return (norm(result), tuple(norm(p) for p in params), variadic)


def _same_type(a: str, b: str) -> bool:
    # C's compatible types, qualifiers aside: calling `void f(T *)` through `void (*)(void *)`
    # is undefined, and accepting it made thousands of candidates for one callback type
    return a == b

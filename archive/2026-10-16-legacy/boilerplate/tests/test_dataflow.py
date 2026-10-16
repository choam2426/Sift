import os
import subprocess
import sys

import pytest
from conftest import FLOW, TARGET, compile_database

from sift import cfamily, dataflow, slices

WINDOWS = "target x86_64-pc-windows-msvc"


@pytest.fixture(scope="module")
def scan(tmp_path_factory):
    db = compile_database(tmp_path_factory.mktemp("flow"), FLOW, ("flow.c", "review.c"))
    return cfamily.scan(FLOW, [db], workers=2, dataflow=True)


@pytest.fixture(scope="module")
def program(scan):
    return dataflow.program(scan, FLOW)


@pytest.fixture(scope="module")
def sinks(program):
    return slices.sinks(program)


@pytest.fixture(scope="module")
def decode(tmp_path_factory):
    """The stage-1 fixtures, whose decode.c reads a length from input and copies with it."""
    db = compile_database(tmp_path_factory.mktemp("target"), TARGET, ("decode.c", "platform.c"))
    return dataflow.program(cfamily.scan(TARGET, [db], workers=2, dataflow=True), TARGET)


def lines(program, name, text, path="flow.c") -> list[int]:
    """Lines of a fixture function that contain `text`."""
    function = next(f for f in program.functions.values() if f.name == name and f.path == path)
    rows = (program.root / path).read_text().split("\n")
    return [n for n in range(function.start_line, function.end_line + 1) if text in rows[n - 1]]


def sink(program, sinks, name, text, kind="subscript", path="flow.c"):
    [line] = lines(program, name, text, path)
    found = [s for s in sinks if s.path == path and s.line == line and s.kind == kind]
    return max(found, key=lambda s: (len(s.code), s.column))  # the outermost on the line


def covered(s) -> set[tuple[str, int]]:
    return {(span.path, n) for span in s.spans for n in range(span.start_line, span.end_line + 1)}


def reasons(s, path, line) -> set[str]:
    return {r for span in s.spans if span.path == path and span.start_line <= line <= span.end_line
            for r in span.reasons}


def test_memcpy_length_read_from_input_reaches_its_definition_and_guard(decode):
    program, sinks = decode, slices.sinks(decode)
    s = slices.slice_of(program, sink(program, sinks, "decode_block", "memcpy(", "call", "decode.c"))
    got = covered(s)
    [guard] = lines(program, "decode_block", "if (in_size < HEADER_SIZE)", "decode.c")
    [length] = lines(program, "decode_block", "length = read_length(in);", "decode.c")
    [callee] = lines(program, "read_length", "return (unsigned)p[0]", "decode.c")
    [exit_] = lines(program, "decode_block", "return -1;", "decode.c")
    [after] = lines(program, "decode_block", "return (int)length;", "decode.c")
    assert {("decode.c", n) for n in (guard, length, callee, exit_)} <= got
    assert ("decode.c", after) not in got
    assert "control dependence" in reasons(s, "decode.c", guard)
    assert "guard exit" in reasons(s, "decode.c", exit_)
    assert "callee return" in reasons(s, "decode.c", length)
    assert "memcpy" in s.models
    assert "memcpy(out, in + HEADER_SIZE, length);  // <- sink: call (memcpy:" in slices.render(program, s)


def test_if_else_short_circuit_guard_and_early_exit(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "guarded", "return buf[i];"))
    got = covered(s)
    for text, reason in [("if (i < 0 || (size_t)i >= n)", "control dependence"),
                         ("return -1;", "guard exit"), ("else", "branch structure")]:
        [n] = lines(program, "guarded", text)
        assert ("flow.c", n) in got and reason in reasons(s, "flow.c", n), text


def test_while_with_continue_and_break(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "scan_until", "return s[i];"))
    got = covered(s)
    expected = lines(program, "scan_until", "i++;") + lines(program, "scan_until", "while (i < limit)") \
        + lines(program, "scan_until", "if (s[i] == ' ')") + lines(program, "scan_until", "break;")
    assert len(expected) == 5 and {("flow.c", n) for n in expected} <= got


def test_do_while(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "sum_down", "total += v[n];"))
    got = covered(s)
    for text in ("do {", "n--;", "} while (n > 0);"):
        assert ("flow.c", lines(program, "sum_down", text)[0]) in got, text
    assert ("flow.c", lines(program, "sum_down", "int total = 0;")[0]) not in got


def test_for_loops_with_omitted_parts(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "first_zero", "return v[i - 1];"))
    got = covered(s)
    expected = lines(program, "first_zero", "i++;") + lines(program, "first_zero", "for (")
    expected += lines(program, "first_zero", "if (i >= n)") + lines(program, "first_zero", "return -1;")
    assert len(expected) == 6 and {("flow.c", n) for n in expected} <= got


def test_switch_with_fallthrough_and_default(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "by_kind", "return p[at];"))
    got = covered(s)
    for text in ("int at = 0;", "switch (kind)", "case 1:", "at = 4;", "case 2:", "at += 2;", "default:",
                 "at = 8;"):
        assert ("flow.c", lines(program, "by_kind", text)[0]) in got, text
    arithmetic = sink(program, sinks, "by_kind", "at += 2;", "integer arithmetic")
    assert arithmetic.detail == "+= in int"


def test_goto_error_paths(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "parse_header", "*out = p[len - 1];"))
    got = covered(s)
    for text in ("if (n < 4)", "len = p[0] | p[1] << 8;", "if (len > n)"):
        assert ("flow.c", lines(program, "parse_header", text)[0]) in got, text
    gotos = lines(program, "parse_header", "goto fail;")
    assert len(gotos) == 2 and all("guard exit" in reasons(s, "flow.c", n) for n in gotos)
    assert ("flow.c", lines(program, "parse_header", "return 0;")[0]) not in got


def test_conditional_operator_comma_and_short_circuit_values(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "pick", "return a[m];"))
    for text in ("int k = (i > j) ? i : j;", "int m = (k++, k * 2);"):
        assert ("flow.c", lines(program, "pick", text)[0]) in covered(s), text
    s = slices.slice_of(program, sink(program, sinks, "nested", "return a[i];"))
    for text in ("int ok = i >= 0 && i < n;", "if (ok)"):
        assert ("flow.c", lines(program, "nested", text)[0]) in covered(s), text


def test_fields_stay_apart_across_calls(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "last", "return b->data[b->len - 1];"))
    got = covered(s)
    assert ("flow.c", lines(program, "last", "set_len(b, len);")[0]) in got
    assert ("flow.c", lines(program, "set_len", "b->len = len;")[0]) in got
    assert ("flow.c", lines(program, "last", "set_cap(b, cap);")[0]) not in got
    assert ("flow.c", lines(program, "set_cap", "b->cap = cap;")[0]) not in got
    summary = program.summary("flow.c:118:set_len")
    # the stored value and the pointer that locates it
    assert summary.outs[("arg*", 0)] == {(".len",): frozenset({(("arg", 0), None), (("arg", 1), None)})}


def test_slices_climb_into_callers_and_descend_into_callees(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "at", "return p[i];"))
    [call] = lines(program, "use_at", "return at(p, j);")
    [j] = lines(program, "use_at", "size_t j = clamp(i, n - 1);")
    [clamp] = lines(program, "clamp", "return n > max ? max : n;")
    assert {("flow.c", n) for n in (call, j, clamp)} <= covered(s)
    assert "argument at caller" in reasons(s, "flow.c", call)
    assert "callee return" in reasons(s, "flow.c", clamp)
    assert program.summary("flow.c:136:clamp").data[("ret",)] == {
        (): frozenset({(("arg", 0), None), (("arg", 1), None)})}
    # which entries reach which of its own sinks, and that its index reaches a memory access
    [(where, entries)] = program.summary("flow.c:141:at").sinks.items()
    assert where[1:] == (143, 12, "subscript") and entries == {("arg", 0), ("arg", 1)}
    assert program.summary("flow.c:146:use_at").reach == {("arg", 0), ("arg", 1), ("arg", 2)}


def test_callee_writes_through_a_pointer_argument(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "copy_block", "memcpy(", "call"))
    got = covered(s)
    assert ("flow.c", lines(program, "copy_block", "read_size(src, &size);")[0]) in got
    assert ("flow.c", lines(program, "read_size", "*size = p[0];")[0]) in got
    [(rel, entries)] = program.summary("flow.c:153:read_size").data[("arg*", 1)].items()
    assert rel == () and {key for key, _ in entries} == {("arg", 0), ("arg*", 0), ("arg", 1)}


def test_indirect_calls_resolve_by_address_taken_signature(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "copy_measured", "memcpy(", "call"))
    got = covered(s)
    assert ("flow.c", lines(program, "measure_short", "return p[0];")[0]) in got
    assert ("flow.c", lines(program, "measure_long", "return (size_t)p[0] << 8 | p[1];")[0]) in got
    [note] = [u for u in s.unresolved if u.kind == "indirect call by signature"]
    assert "2 candidates" in note.detail and "may be incomplete" in note.detail
    [table] = [n for n, row in enumerate((FLOW / "flow.c").read_text().split("\n"), 1)
               if row.startswith("static const measure_fn measures[]")]
    assert "global definition" in reasons(s, "flow.c", table)


def test_external_callee_without_model_is_reported(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "copy_external", "memcpy(", "call"))
    assert {(u.kind, u.detail) for u in s.unresolved} >= {("external callee without model", "external_size")}
    assert "memcpy" in s.models


def test_input_from_library_models_and_entry_points_taints_sinks(program, sinks):
    found = slices.sources(program)
    read = next(src for src in found if src.kind == "library model" and src.detail == "read *1")
    [flow] = slices.taint(program, read, sinks).flows
    assert flow.sink.function == "flow.c:187:read_record" and flow.sink.detail.startswith("memcpy:")
    assert lines(program, "read_record", "size_t n = header[0];")[0] in {span.start_line for span in flow.path}
    entry = next(src for src in found if src.detail == "LLVMFuzzerTestOneInput *0")
    reached = {(f.sink.function, f.sink.code) for f in slices.taint(program, entry, sinks).flows}
    assert ("flow.c:76:parse_header", "p[len - 1]") in reached
    named = slices.sources(program, entry_points={}, functions=("clamp",))
    assert {src.detail for src in named if src.kind == "named function parameter"} == {
        "clamp argument 0", "clamp argument 1"}


def test_integer_conversions_are_sinks_only_when_they_feed_one(program, sinks, decode):
    narrowing = sink(program, sinks, "narrow_copy", "int m = n;", "integer conversion")
    assert narrowing.detail == "narrowing long to int"
    assert WINDOWS not in narrowing.configs and "target i686-linux-gnu" not in narrowing.configs  # 32-bit long
    [argument] = [s for s in sinks if s.function == "flow.c:205:narrow_copy" and s.code == "m"]
    assert argument.kind == "integer conversion" and "sign change int to" in argument.detail
    unused = lines(program, "narrow_copy", "long unused = (short)n;")[0]
    assert not [s for s in sinks if s.path == "flow.c" and s.line == unused]
    returned = lines(decode, "decode_block", "return (int)length;", "decode.c")[0]
    assert not [s for s in slices.sinks(decode) if s.path == "decode.c" and s.line == returned]


def test_globals_written_by_one_callee_and_read_by_another(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "read_limited", "return p[limit];"))
    got = covered(s)
    assert ("flow.c", lines(program, "configure_and_read", "set_limit(n);")[0]) in got
    assert ("flow.c", lines(program, "set_limit", "limit = n;")[0]) in got
    assert {span.reasons for span in s.spans if span.function == ""} == {("global definition",)}
    summary = program.summary("flow.c:215:set_limit")
    [limit] = summary.mods
    assert summary.data[("global", limit)] == {(): frozenset({(("arg", 0), None)})}


def test_facts_carry_the_configurations_that_see_them(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "copy_name", "memcpy(", "call"))
    [guard] = lines(program, "copy_name", "if (n > 16)")
    [span] = [span for span in s.spans if span.start_line == guard]
    assert span.configs == (WINDOWS,)
    assert len(s.sink.configs) == 5


def test_recursion_reaches_a_fixpoint(program):
    assert not program.bounded
    entries = program.summary("flow.c:243:depth").outs[("ret",)][()]
    assert {key for key, _ in entries} == {("arg", 1)}


def test_a_stored_address_is_followed_by_over_approximation(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "alias", "return a[x];"))
    assert ("flow.c", lines(program, "alias", "*q = n;")[0]) in covered(s)


def test_token_budget_cut_keeps_the_nearest_spans_and_reports_the_rest(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "parse_header", "*out = p[len - 1];"))
    full = slices.tokens(slices.render(program, s))
    floor = slices.tokens(slices.render(program, slices.cut(program, s, 0)))  # the sink is always kept
    budget = (floor + full) // 2
    assert floor < budget < full
    cut = slices.cut(program, s, budget)
    assert slices.tokens(slices.render(program, cut)) <= budget
    assert cut == slices.cut(program, s, budget)
    assert cut.dropped and {span.id for span in cut.spans} | {span.id for span in cut.dropped} == {
        span.id for span in s.spans}
    assert all(span.distance == 0 for span in s.spans if span.distance == 0 and span in cut.spans)
    assert any(span.reasons == ("sink",) or "sink" in span.reasons for span in cut.spans)
    assert cut.unresolved[-1].kind == "token budget cut" and "frontier" in cut.unresolved[-1].detail
    nearest = min(span.distance for span in cut.dropped)
    assert all(span in cut.spans for span in s.spans if span.distance < nearest)
    assert slices.cut(program, s, full * 2) == s


def test_cpp_try_catch_and_range_for(program, sinks):
    s = slices.slice_of(program, sink(program, sinks, "guarded_at", "return buf[i];", path="flow.cpp"))
    [guard] = lines(program, "guarded_at", "if (i >= n)", "flow.cpp")
    [throw] = lines(program, "guarded_at", "throw n;", "flow.cpp")
    assert ("flow.cpp", guard) in covered(s) and "guard exit" in reasons(s, "flow.cpp", throw)
    assert any(u.kind == "approximate control flow" for u in s.unresolved)
    s = slices.slice_of(program, sink(program, sinks, "fill", "memset(", "call", "flow.cpp"))
    for name, text in [("fill", "int n = r.total();"), ("Reader::total", "for (int s : sizes)"),
                       ("Reader::total", "t += s;")]:
        assert ("flow.cpp", lines(program, name, text, "flow.cpp")[0]) in covered(s), text


def test_sinks_are_joined_across_configurations_with_stable_ids(program, sinks, decode):
    assert len({s.id for s in sinks}) == len(sinks)
    assert [s.id for s in slices.sinks(program)] == [s.id for s in sinks]
    [memcpy] = [s for s in slices.sinks(decode) if s.function == "decode.c:10:decode_block"]
    assert memcpy.id.startswith("sink:") and len(memcpy.configs) == 5


def test_post_dominators_give_control_dependence():
    # if (a) { b } c: b depends on a, c does not
    succ = [[1, 2], [2], [3], []]
    preds = [[], [0], [0, 1], [2]]
    ipdom = dataflow._idom(preds, succ, 3)
    assert ipdom[0] == 2 and ipdom[1] == 2 and ipdom[2] == 3
    idom = dataflow._idom(succ, preds, 0)
    assert idom[1] == 0 and idom[2] == 0 and idom[3] == 2



def test_a_budget_stops_exploring_without_changing_the_cut(program, sinks):
    s = sink(program, sinks, "at", "return p[i];")
    full = slices.slice_of(program, s)
    budget = 40
    early = slices.slice_of(program, s, budget)
    [bound] = [u for u in early.unresolved if u.kind == "traversal bound"]
    explored = int(bound.detail.split()[3].rstrip(";"))
    assert explored < max(span.distance for span in full.spans)
    assert {span.id for span in early.spans} < {span.id for span in full.spans}
    assert [span.id for span in slices.cut(program, early, budget).spans] == [
        span.id for span in slices.cut(program, full, budget).spans]



def test_the_field_index_keeps_every_dependence(scan, monkeypatch):
    # every call input indexed, against none: summaries and slices must not change
    monkeypatch.setattr(dataflow, "INDEXED", 1)
    indexed = dataflow.program(scan, FLOW)
    monkeypatch.setattr(dataflow, "INDEXED", 10**9)
    plain = dataflow.program(scan, FLOW)
    assert indexed._summaries == plain._summaries
    for a, b in zip(slices.sinks(indexed), slices.sinks(plain), strict=True):
        monkeypatch.setattr(dataflow, "INDEXED", 1)
        got = slices.slice_of(indexed, a)
        monkeypatch.setattr(dataflow, "INDEXED", 10**9)
        assert got == slices.slice_of(plain, b)


# ---- reviews of 2026-10-09 and 2026-10-11: each case lost a definition without a note ------

def review(program, sinks, name, text, kind="subscript"):
    s = slices.slice_of(program, sink(program, sinks, name, text, kind, "review.c"))
    return s, {n for path, n in covered(s) if path == "review.c"}


def at(program, name, text) -> int:
    [line] = lines(program, name, text, "review.c")
    return line


def noise_absent(program, name, got):
    """Neither the value no sink reads nor a write after the sink: a flow-insensitive or
    one-class analysis would include the second."""
    assert at(program, name, "int noise") not in got
    after = lines(program, name, "/* after */", "review.c")
    assert not set(after) & got, after


@pytest.mark.parametrize("name, sink_text, needed", [
    ("copy_then_write", "int r = a[*x];", [("copy_then_write", "*y = n;")]),
    ("array_alias", "int r = a[p[1]];", [("array_alias", "buf[1] = n;")]),
    ("alias_in_callee", "int r = a[c->len];", [("alias_in_callee", "init2(c, n);"), ("init2", "e->len = n;")]),
    ("field_alias_in_callee", "int r = a[c->b->len];",
     [("field_alias_in_callee", "init3(c, n);"), ("init3", "b->len = n;")]),
    ("conditional_argument", "int r = a[*p];",
     [("conditional_argument", "fill(c ? p : q, n);"), ("fill", "*p = n;")]),
    ("same_callee_results", "int r = a[get()->len];", [("same_callee_results", "get()->len = n;")]),
])
def test_pointer_copies_carry_what_they_point_to(program, sinks, name, sink_text, needed):
    s, got = review(program, sinks, name, sink_text)
    for function, text in needed:
        assert at(program, function, text) in got, text
    noise_absent(program, name, got)


def test_pointer_increments_keep_writes_through_the_pointer(program, sinks):
    s, got = review(program, sinks, "increment_keeps_writes", "int r = arr[p[0]];")
    assert at(program, "increment_keeps_writes", "p[1] = n;") in got
    noise_absent(program, "increment_keeps_writes", got)
    s, got = review(program, sinks, "increment_in_callee", "int r = arr[p[1]];")
    assert {at(program, "increment_in_callee", "w2(p, n);"), at(program, "w2", "p[1] = n;")} <= got
    noise_absent(program, "increment_in_callee", got)


@pytest.mark.parametrize("name, sink_text", [
    ("struct_copy", "int r = a[t.d[0]];"), ("struct_return", "int r = a[t.d[0]];"),
])
def test_struct_copies_carry_what_their_pointers_point_to(program, sinks, name, sink_text):
    s, got = review(program, sinks, name, sink_text)
    assert at(program, name, "p->d[0] = n;") in got
    noise_absent(program, name, got)


def test_struct_arguments_carry_what_their_pointers_point_to(program, sinks):
    s, got = review(program, sinks, "use3", "return a[t.d[0]];")
    assert {at(program, "struct_argument", "int r = use3(*p, a);"),
            at(program, "struct_argument", "p->d[0] = n;")} <= got
    noise_absent(program, "struct_argument", got)


def test_input_models_write_their_outputs(program, sinks):
    s, got = review(program, sinks, "read_with_scanf", "int r = a[n];")
    assert {at(program, "read_with_scanf", 'scanf("%d", &n);'), at(program, "read_with_scanf", "int n = 0;")} <= got
    noise_absent(program, "read_with_scanf", got)
    assert "scanf" in s.models


def test_function_tables_in_static_locals_are_address_taken(program, sinks):
    s, got = review(program, sinks, "static_table", "int r = a[table[w](v)];")
    assert at(program, "hidden", "return v + 1;") in got
    [note] = [u for u in s.unresolved if u.kind == "indirect call by signature"]
    assert "2 candidates" in note.detail and "may be incomplete" in note.detail
    noise_absent(program, "static_table", got)


def test_inline_assembly_writes_its_operands_and_notes_are_function_wide(program, sinks):
    s, got = review(program, sinks, "asm_output", "int r = arr[n];")
    assert at(program, "asm_output", "__asm__") in got
    noise_absent(program, "asm_output", got)
    s, got = review(program, sinks, "asm_elsewhere", "return arr[x];")
    assert at(program, "asm_elsewhere", "__asm__") not in got
    assert any(u.kind == "unmodeled" and "assembly" in u.detail for u in s.unresolved)


def test_rendering_keeps_exits_breaks_and_labels(program, sinks):
    s, got = review(program, sinks, "abort_guard", "int r = a[n];")
    assert {at(program, "abort_guard", "if (n > 10)"), at(program, "abort_guard", "abort();")} <= got
    noise_absent(program, "abort_guard", got)
    s, got = review(program, sinks, "switch_arms", "int r = a[at];")
    assert {at(program, "switch_arms", "break;"), at(program, "switch_arms", "goto out;"),
            at(program, "switch_arms", "out:")} <= got
    noise_absent(program, "switch_arms", got)
    text = slices.render(program, s)
    assert text.index("at = n;") < text.index("break;") < text.index("goto out;")


def test_functions_that_never_return_are_inferred(program, sinks):
    s, got = review(program, sinks, "inferred_guard", "int r = a[n];")
    guard, call = at(program, "inferred_guard", "if (n > 10)"), at(program, "inferred_guard", 'fatal("too big");')
    assert {guard, call} <= got
    assert "guard exit (callee inferred not to return)" in reasons(s, "review.c", call)
    assert any(program.functions[f].name == "fatal" for f in program.noreturn)
    noise_absent(program, "inferred_guard", got)


def test_fortified_builtins_use_their_own_argument_layout(program, sinks):
    assert program.model("__builtin___snprintf_chk") == "__snprintf_chk"
    assert program.model("__builtin___memcpy_chk") == "memcpy"
    assert program.model("__isoc99_sscanf") == "sscanf"
    [s] = [s for s in sinks if s.path == "review.c" and s.line == at(program, "fortified", "snprintf(")
           and s.kind == "call"]
    assert all("format" in detail for detail in s.detail.split(" | "))


def test_writes_to_one_of_several_objects_are_weak(program, sinks):
    s, got = review(program, sinks, "strong_two_locals", "int r = arr[x];")
    assert at(program, "strong_two_locals", "int x = secret, y = 1;") in got
    noise_absent(program, "strong_two_locals", got)
    summary = program.summary(next(f for f, fn in program.functions.items() if fn.name == "param_in_class"))
    assert ("arg", 2) in {key for key, _ in summary.outs[("ret",)][()]}
    s, got = review(program, sinks, "globals_in_class", "int r = arr[g_lo];")
    assert at(program, "set_lo", "g_lo = v;") in got
    noise_absent(program, "globals_in_class", got)


def test_a_global_written_through_a_local_pointer_is_exported(program, sinks):
    s, got = review(program, sinks, "read_counter", "return arr[counter];")
    assert at(program, "set_through_local", "*p = n;") in got
    noise_absent(program, "set_through_local", got)


def test_pointers_to_pointers_join_what_they_point_to(program, sinks):
    s, got = review(program, sinks, "ptr_to_ptr", "int r = arr[*p];")
    assert at(program, "ptr_to_ptr", "x = n;") in got
    noise_absent(program, "ptr_to_ptr", got)


@pytest.mark.parametrize("name, sink_text", [
    ("returned_into_argument", "int r = arr[buf[1]];"), ("returned_by_model", "int r = arr[s[3]];"),
    ("returned_into_member", "int r = arr[b->it.v];"), ("returned_into_buffer", "int r = arr[l->text[2]];"),
])
def test_returned_pointers_may_point_into_arguments(program, sinks, name, sink_text):
    s, got = review(program, sinks, name, sink_text)
    assert at(program, name, "= n;") in got
    noise_absent(program, name, got)


@pytest.mark.parametrize("name, writer", [
    ("escaped_through_callee", "fill_held(&h, n);"), ("escaped_through_global", "poke(n);"),
])
def test_escaped_addresses_may_be_written_by_later_calls(program, sinks, name, writer):
    s, got = review(program, sinks, name, "int r = arr[x];")
    assert at(program, name, writer) in got
    noise_absent(program, name, got)


def test_global_writes_reach_callers_of_unsummarized_calls(scan, monkeypatch):
    # one round per function on average: ping and pong stop at the bound, two_levels_up does not
    monkeypatch.setattr(dataflow, "MAX_ROUNDS", 1)
    monkeypatch.setattr(dataflow, "MAX_CANDIDATES", 1)
    limited = dataflow.program(scan, FLOW)
    name = lambda f: limited.functions[f].name
    assert {"ping", "pong"} <= {name(f) for f in limited.bounded}
    assert "two_levels_up" not in {name(f) for f in limited.bounded}
    found = slices.sinks(limited)
    s, got = review(limited, found, "two_levels_up", "int r = arr[depth_g];")
    assert at(limited, "ping", "depth_g = n;") in got
    assert any(u.kind == "summary round bound" and u.line == at(limited, "two_levels_up", "enter(n);")
               for u in s.unresolved)
    noise_absent(limited, "two_levels_up", got)
    s, got = review(limited, found, "through_dispatch", "int r = arr[disp_g];")
    assert {at(limited, "handler_a", "disp_g = x;"), at(limited, "handler_b", "disp_g = x + 1;")} <= got
    noise_absent(limited, "through_dispatch", got)


def test_one_object_for_two_parameters(program, sinks):
    s, got = review(program, sinks, "both_ptrs", "return arr[*q];")
    assert at(program, "both_ptrs", "*p = n;") in got
    assert any(u.kind == "same object for two parameters" for u in s.unresolved)
    noise_absent(program, "both_ptrs", got)


def test_a_callee_that_may_abort_guards_what_follows(program, sinks):
    s, got = review(program, sinks, "conditional_abort", "int r = arr[k];")
    call = at(program, "conditional_abort", "check_or_abort(c);")
    assert call in got
    assert "callee may not return depending on argument" in reasons(s, "review.c", call)
    summary = program.summary(next(f for f, fn in program.functions.items() if fn.name == "check_or_abort"))
    assert summary.halts == {(("arg", 0), None)}
    noise_absent(program, "conditional_abort", got)


def test_widening_notes_do_not_depend_on_what_was_sliced_before(scan):
    fresh = dataflow.program(scan, FLOW)
    found = slices.sinks(fresh)
    first = sink(fresh, found, "widening", "int x = a[i];", path="review.c")
    through = sink(fresh, found, "widening", "return a[deep(", path="review.c")
    note = lambda s: any("through a call" in u.detail for u in s.unresolved)
    before = slices.slice_of(fresh, first)
    assert note(slices.slice_of(fresh, through))
    assert slices.slice_of(fresh, first) == before and not note(before)


def test_slices_do_not_depend_on_the_hash_seed(tmp_path):
    script = f"""
import json, sys
from pathlib import Path
from sift import cfamily, dataflow, slices
root = Path({str(FLOW)!r})
db = Path(sys.argv[1]) / "cc.json"
db.write_text(json.dumps([{{"directory": str(root), "file": n, "arguments": ["cc", "-std=gnu11", "-c", n]}}
                          for n in ("flow.c", "review.c")]))
if __name__ == "__main__":
    p = dataflow.program(cfamily.scan(root, [db], workers=2, dataflow=True), root)
    for s in slices.sinks(p):
        sl = slices.slice_of(p, s)
        print(s.id, [(x.id, x.reasons, x.parent, x.distance, x.configs) for x in sl.spans],
              [(u.kind, u.detail, u.line) for u in sl.unresolved], sl.models)
"""
    path = tmp_path / "run.py"
    path.write_text(script)
    outputs = []
    for seed in ("1", "2", "3"):
        done = subprocess.run([sys.executable, str(path), str(tmp_path)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONHASHSEED": seed}, check=True)
        outputs.append(done.stdout)
    assert outputs[0] and outputs[0] == outputs[1] == outputs[2]


def test_control_dependences_of_real_functions(program):
    def controlling(name, line, path="flow.c"):
        v = program.of[next(f for f, fn in program.functions.items() if fn.name == name)][0]
        nodes = [n for n, nd in enumerate(v.nodes) if nd[2] == line and nd[0] in ("stmt", "cond", "return")]
        return {v.nodes[a][2] for n in nodes for a, _ in v.control[n]} - {line}
    line = lambda name, text: lines(program, name, text)
    assert controlling("guarded", line("guarded", "return buf[i];")[0]) == set(line("guarded", "if (i < 0"))
    # directly on the test whose false edge leads here, not on the tests before it
    [space, zero] = line("scan_until", "if (s[i]")
    [_, last] = line("scan_until", "i++;")
    assert controlling("scan_until", last) == {zero}
    assert controlling("scan_until", zero) == {space}
    assert controlling("scan_until", line("scan_until", "return s[i];")[0]) == set()
    assert controlling("first_zero", line("first_zero", "return v[i - 1];")[0]) == set(line("first_zero", "if (v[i] == 0)"))
    assert controlling("first_zero", line("first_zero", "if (v[i] == 0)")[0]) == set(line("first_zero", "if (i >= n)"))


def test_for_headers_with_comments_and_cpp17_if_init(program, sinks):
    # a `;` inside a comment in the header must not move the condition
    v = program.of[next(f for f, fn in program.functions.items() if fn.name == "for_comment")][0]
    header, body = at(program, "for_comment", "for (i = 0;"), at(program, "for_comment", "s += a[i++];")
    for n in [n for n, nd in enumerate(v.nodes) if nd[2] == body]:
        assert {(v.nodes[a][0], v.nodes[a][2]) for a, _ in v.control[n]} == {("cond", header)}
    # the condition is `n > 10`, read from the parameter, not the init statement's value
    v = program.of[next(f for f, fn in program.functions.items() if fn.name == "init_if")][0]
    [line] = lines(program, "init_if", "if (k = n * 2; n > 10)", "flow.cpp")
    [cond] = [n for n, nd in enumerate(v.nodes) if nd[2] == line and nd[0] == "cond"]
    assert {v.slot_port[t] for t, _, _ in v.deps[cond]} == {("fin", ("arg", 1))}

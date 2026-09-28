from conftest import TARGET

from sift import cfamily


def scan(compile_db):
    return cfamily.scan(TARGET, [compile_db], workers=2)


def test_finds_definitions_in_every_reachable_configuration(compile_db):
    functions = {f.id: f for f in scan(compile_db).functions}
    assert set(functions) == {
        "decode.c:5:read_length", "decode.c:10:decode_block", "decode.c:20:find_marker",
        "platform.c:5:read_random",    # only under _WIN32
        "platform.c:10:read_random",
        "platform.c:18:feature",       # only with SIFT_FEATURE defined
        "platform.c:32:after_macros",
        "platform.c:39:spaced",        # `#  ifdef`
        "platform.c:44:nested",        # needs two macros defined at once
        # not in the compile database, and borrows C flags (-std=gnu11) that a C++ parse rejects
        "table.cpp:5:store::Table::~Table", "table.cpp:6:store::Table::size",
        "table.cpp:14:store::Table::row",
        "table.cpp:21:Pair::first", "table.cpp:22:Pair::second",  # partial specialization
        "table.cpp:23:operator==",     # friend defined in a class
    }
    assert "target x86_64-pc-windows-msvc" in functions["platform.c:5:read_random"].configs
    assert functions["platform.c:18:feature"].configs == ("-DSIFT_FEATURE=1",)
    assert functions["table.cpp:14:store::Table::row"].configs[0] == "borrowed flags"


def test_code_is_the_exact_source_text(compile_db):
    for f in scan(compile_db).functions:
        lines = (TARGET / f.path).read_text().splitlines()
        assert f.code in "\n".join(lines[f.start_line - 1:f.end_line])


def test_statement_macros_do_not_move_the_end(compile_db):
    # tree-sitter ended bodies thousands of lines late around `PRF_STR("x")` (7-Zip XzDec.c)
    functions = {f.id: f for f in scan(compile_db).functions}
    assert functions["platform.c:32:after_macros"].end_line == 36
    assert functions["platform.c:10:read_random"].end_line == 14


def test_reports_what_no_configuration_reached(compile_db):
    unanalyzed = {(u.path, u.start_line, u.name, u.reason) for u in scan(compile_db).unanalyzed}
    assert ("platform.c", 25, "disabled", "inactive in every configuration") in unanalyzed
    assert ("unused.h", 1, "unused", "no configuration parsed this file") in unanalyzed


def test_reports_only_code_that_no_evaluated_function_contains(compile_db):
    result = scan(compile_db)
    spans = {(f.path, n) for f in result.functions for n in range(f.start_line, f.end_line + 1)}
    for u in result.unanalyzed:
        lines = (TARGET / u.path).read_text().splitlines()[u.start_line - 1:u.end_line]
        assert not {(u.path, n) for n in range(u.start_line, u.end_line + 1)} & spans, u
        assert any(line.strip() and not line.strip().startswith("#") for line in lines), u

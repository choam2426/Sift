from pathlib import Path

from sift import code

TARGET = Path(__file__).parent / "fixtures" / "target"


def test_finds_every_definition_with_its_location():
    found = code.functions(TARGET)
    assert [f.id for f in found] == [
        "decode.c:5:read_length",
        "decode.c:10:decode_block",
        "decode.c:20:find_marker",
        "table.cpp:5:~Table",
        "table.cpp:6:size",
        "table.cpp:14:Table::row",
    ]
    assert not any(f.parse_error for f in found)


def test_code_is_the_source_text_at_its_location():
    for f in code.functions(TARGET):
        lines = (TARGET / f.path).read_text().splitlines()
        assert f.code in "\n".join(lines[f.start_line - 1:f.end_line])


def test_marks_definitions_that_did_not_parse():
    [broken] = code.functions_in(b"int f(void) { return (1; }", "x.c", code.C)
    assert broken.name == "f" and broken.parse_error


def test_names_made_by_macros_keep_the_macro_call():
    source = b"static int PTRCALL\nPREFIX(scanComment)(const char *p)\n{\n  return 0;\n}\n"
    [f] = code.functions_in(source, "x.c", code.C)
    assert f.name == "PREFIX(scanComment)"


def test_statements_misread_as_definitions_are_dropped():
    # a statement macro without a semicolon makes tree-sitter see `if (...) {...}` as a definition
    source = b"int f(int x)\n{\n  RINOK(x)\n  if (x) { return 1; }\n  return 0;\n}\n"
    assert all(f.name not in code.KEYWORDS for f in code.functions_in(source, "x.c", code.C))


def test_statement_macro_without_semicolon_does_not_extend_the_body():
    # 7-Zip XzDec.c: PRF_STR(...) made tree-sitter end MixCoder_Code 2,000 lines late
    source = b'int f(int x)\n{\n  PRF_STR("a")\n  x = 1;\n  return x;\n}\n\nint g(void)\n{\n  return 0;\n}\n'
    assert [(f.name, f.end_line) for f in code.functions_in(source, "x.c", code.C)] == [("f", 6), ("g", 11)]


def test_braces_in_comments_literals_and_else_branches_are_ignored():
    source = (b"int f(int x)\n{\n  /* { */ char c = '{';\n  const char *s = \"}{\";\n"
              b"#if A\n  x = 1;\n#else\n  }\n#endif\n  PRF_STR(s)\n  return c;\n}\n")
    [f] = code.functions_in(source, "x.c", code.C)
    assert f.end_line == 12

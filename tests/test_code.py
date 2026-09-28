from sift import code


def test_estimates_names_made_by_macros_keep_the_macro_call():
    source = b"static int PTRCALL\nPREFIX(scanComment)(const char *p)\n{\n  return 0;\n}\n"
    [d] = code.definitions_in(source, "x.c", code.C)
    assert d.name == "PREFIX(scanComment)"


def test_estimates_drop_statements_misread_as_definitions():
    # a statement macro without a semicolon makes tree-sitter see `if (...) {...}` as a definition
    source = b"int f(int x)\n{\n  RINOK(x)\n  if (x) { return 1; }\n  return 0;\n}\n"
    names = [d.name for d in code.definitions_in(source, "x.c", code.C)]
    assert names == ["f"]

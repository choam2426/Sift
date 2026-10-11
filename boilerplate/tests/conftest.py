import json
from pathlib import Path

import pytest

from sift import cfamily

TARGET = Path(__file__).parent / "fixtures" / "target"
FLOW = Path(__file__).parent / "fixtures" / "flow"  # dataflow fixtures; flow.cpp borrows flags


@pytest.fixture
def compile_db(tmp_path) -> Path:
    """A compile database for the C fixtures; table.cpp and unused.h are deliberately left out."""
    return compile_database(tmp_path, TARGET, ("decode.c", "platform.c"))


def compile_database(directory: Path, root: Path, names) -> Path:
    try:
        cfamily.libclang_path()
    except RuntimeError as error:
        pytest.skip(str(error))
    db = directory / "compile_commands.json"
    db.write_text(json.dumps([{"directory": str(root), "file": name, "arguments": ["cc", "-std=gnu11", "-c", name, "-o", "x.o"]}
                              for name in names]))
    return db

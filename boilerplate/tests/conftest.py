import json
from pathlib import Path

import pytest

from sift import cfamily

TARGET = Path(__file__).parent / "fixtures" / "target"


@pytest.fixture
def compile_db(tmp_path) -> Path:
    """A compile database for the C fixtures; table.cpp and unused.h are deliberately left out."""
    try:
        cfamily.libclang_path()
    except RuntimeError as error:
        pytest.skip(str(error))
    db = tmp_path / "compile_commands.json"
    db.write_text(json.dumps([{"directory": str(TARGET), "file": name, "arguments": ["cc", "-std=gnu11", "-c", name, "-o", "x.o"]}
                              for name in ("decode.c", "platform.c")]))
    return db

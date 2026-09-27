"""Stage 1 end to end through the CLI, with a fake Jev that scores by function name."""

import json
from pathlib import Path

import httpx

from sift.cli import main

TARGET = Path(__file__).parent / "fixtures" / "target"
SCORES = {"decode_block": 0.87, "find_marker": 0.60, "Table::row": 0.64, "read_length": 0.31}


def fake_jev(calls):
    def handler(request):
        state = json.loads(request.content)["state"]
        calls.append(state)
        if "~Table" in state:
            return httpx.Response(400, text='{"error": "max_tokens_exceeded"}')
        score = next((s for name, s in SCORES.items() if name in state), 0.1)
        return httpx.Response(200, json={"model": "jev-1.13.0", "usage": {"input_tokens": 10},
                                         "answers": {"review_worth_plain": {"type": "noul", "noul": score}}})
    return httpx.MockTransport(handler)


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_selects_and_ranks_functions_at_or_above_the_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "key")
    calls = []
    assert main(["triage", str(TARGET), "--run", str(tmp_path)], transport=fake_jev(calls)) == 0

    selected = [row["function_id"] for row in read(tmp_path / "selected.jsonl")]
    assert selected == ["decode.c:10:decode_block", "table.cpp:14:Table::row", "decode.c:20:find_marker"]
    summary = json.loads((tmp_path / "manifest.json").read_text())["summary"]
    assert summary | {"input_tokens": 0} == {
        "functions": 6, "parse_error": 0, "scored": 5, "unscored": 1, "error": 0,
        "unsent": 0, "selected": 3, "input_tokens": 0, "stopped": None}
    assert summary["input_tokens"] == 50


def test_rerun_resumes_from_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "key")
    calls = []
    main(["triage", str(TARGET), "--run", str(tmp_path), "--max-requests", "2"], transport=fake_jev(calls))
    assert json.loads((tmp_path / "manifest.json").read_text())["summary"]["unsent"] == 4

    assert main(["triage", str(TARGET), "--run", str(tmp_path)], transport=fake_jev(calls)) == 0
    assert len(calls) == 6  # 2 first, then only the 4 that were not sent


def test_estimate_needs_no_key_and_sends_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert main(["triage", str(TARGET), "--run", str(tmp_path), "--estimate"]) == 0
    assert json.loads(capsys.readouterr().out)["functions"] == 6

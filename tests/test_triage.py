"""Stage 1 end to end through the CLI, with a fake Jev that scores by function name."""

import json

import httpx
from conftest import TARGET

from sift.cli import main

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


def triage(run, compile_db, *extra):
    return ["triage", str(TARGET), "--compile-db", str(compile_db), "--run", str(run), *extra]


def test_selects_and_ranks_functions_at_or_above_the_threshold(tmp_path, compile_db, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "key")
    run = tmp_path / "run"
    assert main(triage(run, compile_db), transport=fake_jev([])) == 0

    selected = [row["function_id"] for row in read(run / "selected.jsonl")]
    assert selected == ["decode.c:10:decode_block", "table.cpp:14:store::Table::row", "decode.c:20:find_marker"]
    summary = json.loads((run / "manifest.json").read_text())["summary"]
    assert (summary["functions"], summary["scored"], summary["unscored"], summary["selected"]) == (15, 14, 1, 3)
    assert summary["input_tokens"] == 140 and summary["stopped"] is None
    assert any(row["reason"] == "no configuration parsed this file" for row in read(run / "unanalyzed.jsonl"))


def test_rerun_resumes_from_the_cache(tmp_path, compile_db, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "key")
    run, calls = tmp_path / "run", []
    main(triage(run, compile_db, "--max-requests", "2"), transport=fake_jev(calls))
    assert json.loads((run / "manifest.json").read_text())["summary"]["unsent"] == 13

    assert main(triage(run, compile_db), transport=fake_jev(calls)) == 0
    assert len(calls) == 15  # 2 first, then only the 13 that were not sent


def test_estimate_needs_no_key_and_sends_nothing(tmp_path, compile_db, capsys, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert main(triage(tmp_path / "run", compile_db, "--estimate")) == 0
    assert json.loads(capsys.readouterr().out)["functions"] == 15

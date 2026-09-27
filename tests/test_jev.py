import asyncio
import json
from pathlib import Path

import httpx

from sift.jev import Jev

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "jev-response.json").read_text())
QUESTIONS = {"review_worth_plain": {"type": "noul", "instructions": "?"}}


def ask(tmp_path, responses, states=("int f(void);",), **options):
    """Send each state through a fake API that replays `responses` in order."""
    replies, sent = list(responses), []

    def handler(request):
        sent.append(json.loads(request.content))
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    async def go():
        jev = Jev("key", tmp_path / "cache.jsonl", transport=httpx.MockTransport(handler),
                  retry_delay=0, **options)
        try:
            return [await jev.ask(s, QUESTIONS) for s in states], jev, sent
        finally:
            await jev.close()

    return asyncio.run(go())


def test_parses_a_recorded_response(tmp_path):
    [result], _, sent = ask(tmp_path, [(200, RECORDED)])
    assert (result.status, result.scores, result.model) == ("scored", {"review_worth_plain": 0.71}, "jev-1.13.0")
    assert sent[0] == {"model": "jev-1.13.0", "state": "int f(void);", "questions": QUESTIONS}


def test_cached_results_are_not_resent(tmp_path):
    ask(tmp_path, [(200, RECORDED)])
    [result], _, sent = ask(tmp_path, [])
    assert result.cached and result.scores == {"review_worth_plain": 0.71} and sent == []


def test_input_over_the_limit_is_unscored_not_an_error(tmp_path):
    [result], _, _ = ask(tmp_path, [(400, '{"error": "max_tokens_exceeded"}')])
    assert (result.status, result.detail) == ("unscored", "max_tokens_exceeded")


def test_retries_transient_errors(tmp_path):
    [result], _, sent = ask(tmp_path, [(429, "slow down"), (503, "busy"), (200, RECORDED)])
    assert result.status == "scored" and len(sent) == 3


def test_account_error_stops_every_later_request(tmp_path):
    results, jev, sent = ask(tmp_path, [(402, "payment required")], states=("a", "b", "c"))
    assert [r.status for r in results] == ["error", "unsent", "unsent"]
    assert jev.stopped == "HTTP 402" and len(sent) == 1


def test_request_budget_is_enforced(tmp_path):
    results, jev, sent = ask(tmp_path, [(200, RECORDED)] * 3, states=("a", "b", "c"), max_requests=2)
    assert [r.status for r in results] == ["scored", "scored", "unsent"]
    assert jev.stopped == "request budget used up" and len(sent) == 2


def test_errors_are_not_cached(tmp_path):
    ask(tmp_path, [(500, "x")] * 5)
    [result], _, sent = ask(tmp_path, [(200, RECORDED)])
    assert result.status == "scored" and len(sent) == 1


def test_rejects_malformed_answers(tmp_path):
    bad = {"model": "jev-1.13.0", "answers": {"review_worth_plain": {"noul": 1.5}}}
    [result], _, _ = ask(tmp_path, [(200, bad)])
    assert (result.status, result.detail) == ("error", "invalid response")

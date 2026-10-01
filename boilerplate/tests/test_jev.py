import asyncio
import json
from pathlib import Path

import httpx

from sift.jev import Jev

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "jev-response.json").read_text())
QUESTIONS = {"review_worth_plain": {"type": "noul", "instructions": "?"}}


def ask(tmp_path, responses, states=("int f(void);",), questions=QUESTIONS, **options):
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
            return [await jev.ask(s, questions) for s in states], jev, sent
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


CHOICE = {"kind": {"type": "choice", "instructions": "?", "criteria": {"bug": "a", "fine": "b"}}}


def test_choice_answers_are_scored_per_option(tmp_path):
    answer = {"choice": "bug", "probabilities": {"bug": 0.7, "fine": 0.3}, "confidence": 0.4}
    reply = {"model": "jev-1.13.0", "answers": {"review_worth_plain": {"noul": 0.6}, "kind": answer}}
    [result], _, _ = ask(tmp_path, [(200, reply)], questions={**QUESTIONS, **CHOICE})
    assert result.scores == {"review_worth_plain": 0.6, "kind/bug": 0.7, "kind/fine": 0.3}


def test_choice_answers_with_other_options_are_rejected(tmp_path):
    reply = {"model": "jev-1.13.0", "answers": {"kind": {"choice": "x", "probabilities": {"x": 1.0}}}}
    [result], _, _ = ask(tmp_path, [(200, reply)], questions=CHOICE)
    assert (result.status, result.detail) == ("error", "invalid response")


def test_the_same_state_asked_at_once_is_sent_once(tmp_path):
    sent = []

    async def handler(request):
        sent.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=RECORDED)

    async def go():
        jev = Jev("key", tmp_path / "cache.jsonl", transport=httpx.MockTransport(handler))
        try:
            return await asyncio.gather(jev.ask("int f(void);", QUESTIONS), jev.ask("int f(void);", QUESTIONS))
        finally:
            await jev.close()

    first, second = asyncio.run(go())
    assert len(sent) == 1 and first.scores == second.scores and second.cached


def test_a_cache_line_cut_short_by_an_interruption_is_ignored(tmp_path):
    ask(tmp_path, [(200, RECORDED)])
    with (tmp_path / "cache.jsonl").open("a") as cache:
        cache.write('{"key": "cut sh')
    [result, _], _, sent = ask(tmp_path, [(200, RECORDED)], states=("int f(void);", "int g(void);"))
    assert result.cached and len(sent) == 1
    [_, again], _, sent = ask(tmp_path, [], states=("int f(void);", "int g(void);"))
    assert again.cached and sent == []  # the result written after the cut line survived

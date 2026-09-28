"""Stage 1: score every function with one Jev question and select the project's top share (ADR 0004)."""

import asyncio
import math
from dataclasses import dataclass, replace

from sift.code import Function
from sift.jev import MODEL, Jev

QUESTION_ID = "review_worth_plain"
QUESTIONS = {QUESTION_ID: {
    "type": "noul",
    "instructions": "Is this function worth a security researcher's time to inspect further for bugs?",
}}
THRESHOLD = 0.60  # floor, calibrated for MODEL, QUESTIONS and function-code-only input
TOP_SHARE = 0.15  # of the project's functions; scores run higher in some projects than others


@dataclass(frozen=True)
class Triaged:
    function_id: str
    status: str  # scored | unscored | error | unsent
    score: float | None
    detail: str
    input_tokens: int = 0
    selected: bool = False


async def triage(functions: list[Function], jev: Jev) -> list[Triaged]:
    results = await asyncio.gather(*(jev.ask(f.code, QUESTIONS) for f in functions))
    return select([_triaged(f, r) for f, r in zip(functions, results, strict=True)])


def select(triaged: list[Triaged]) -> list[Triaged]:
    """Mark functions at or above THRESHOLD that also rank in the project's TOP_SHARE."""
    budget = math.ceil(TOP_SHARE * len(triaged))
    passing = sorted((t for t in triaged if t.score is not None and t.score >= THRESHOLD),
                     key=lambda t: (-t.score, t.function_id))
    chosen = {t.function_id for t in passing[:budget]}
    return [replace(t, selected=t.function_id in chosen) for t in triaged]


def ranked(triaged: list[Triaged]) -> list[Triaged]:
    """Selected functions, highest score first, ties by id."""
    return sorted((t for t in triaged if t.selected), key=lambda t: (-t.score, t.function_id))


def _triaged(function, result) -> Triaged:
    tokens = (result.usage or {}).get("input_tokens", 0) if not result.cached else 0
    if result.status != "scored":
        return Triaged(function.id, result.status, None, result.detail, tokens)
    if result.model != MODEL:  # the threshold does not carry over to another model
        return Triaged(function.id, "error", None, f"model {result.model} != {MODEL}", tokens)
    return Triaged(function.id, "scored", result.scores[QUESTION_ID], "", tokens)

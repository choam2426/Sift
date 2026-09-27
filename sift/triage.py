"""Stage 1: score every function with one Jev question and keep those at or above the threshold (ADR 0004)."""

import asyncio
from dataclasses import dataclass

from sift.code import Function
from sift.jev import MODEL, Jev

QUESTION_ID = "review_worth_plain"
QUESTIONS = {QUESTION_ID: {
    "type": "noul",
    "instructions": "Is this function worth a security researcher's time to inspect further for bugs?",
}}
THRESHOLD = 0.60  # calibrated for MODEL, QUESTIONS and function-code-only input


@dataclass(frozen=True)
class Triaged:
    function_id: str
    status: str  # scored | unscored | error | unsent
    score: float | None
    detail: str
    input_tokens: int = 0

    @property
    def selected(self) -> bool:
        return self.score is not None and self.score >= THRESHOLD


async def triage(functions: list[Function], jev: Jev) -> list[Triaged]:
    results = await asyncio.gather(*(jev.ask(f.code, QUESTIONS) for f in functions))
    return [_triaged(f, r) for f, r in zip(functions, results)]


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

"""Stage 1: score every function with one Jev question, then select by a floor and a top share.

The floor and the share are parameters the agent and the user choose for the target
(spec P-SELECT); Sift's own experiments used 0.60 and 15%.
"""

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


@dataclass(frozen=True)
class Triaged:
    function_id: str
    status: str  # scored | unscored | error | unsent
    score: float | None
    detail: str
    input_tokens: int = 0
    selected: bool = False


async def triage(functions: list[Function], jev: Jev, floor: float, share: float) -> list[Triaged]:
    results = await asyncio.gather(*(jev.ask(f.code, QUESTIONS) for f in functions))
    return select([_triaged(f, r) for f, r in zip(functions, results, strict=True)], floor, share)


def select(triaged: list[Triaged], floor: float, share: float) -> list[Triaged]:
    """Mark functions scoring at least `floor` that also rank in the target's top `share`."""
    budget = math.ceil(share * len(triaged))
    passing = sorted((t for t in triaged if t.score is not None and t.score >= floor),
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
    if result.model != MODEL:  # score distributions, and so the chosen floor, differ per model
        return Triaged(function.id, "error", None, f"model {result.model} != {MODEL}", tokens)
    return Triaged(function.id, "scored", result.scores[QUESTION_ID], "", tokens)

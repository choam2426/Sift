"""Jev client: one place for request limits, budget, caching and error classes."""

import asyncio
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
RETRY_STATUS = {408, 429, 500, 502, 503, 504, 529}
STOP_STATUS = {401, 402, 403}  # account problems: every later request would fail too
ATTEMPTS = 5


@dataclass(frozen=True)
class Result:
    status: str  # scored | unscored (input over the model limit) | error | unsent
    scores: dict[str, float] = field(default_factory=dict)
    model: str | None = None
    detail: str = ""
    usage: dict | None = None
    cached: bool = False


class Jev:
    """Ask Noul questions about one state per request.

    Scored and unscored results are cached by (model, state, questions), so a rerun
    resumes without resending. Once an account error occurs or max_requests is used
    up, `stopped` holds the reason and every later ask returns `unsent`.
    """

    def __init__(self, key: str, cache: Path, *, concurrency: int = 16,
                 max_requests: int | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 retry_delay: float = 1.0):
        self._http = httpx.AsyncClient(headers={"Authorization": "Bearer " + key},
                                       timeout=90, transport=transport)
        self._limit = asyncio.Semaphore(concurrency)
        self._cache_path = cache
        self._cache = _load(cache)
        self._remaining = max_requests
        self._retry_delay = retry_delay
        self.sent = 0
        self.stopped: str | None = None

    async def ask(self, state: str, questions: dict[str, dict]) -> Result:
        key = _key(state, questions)
        if key in self._cache:
            return Result(**self._cache[key], cached=True)
        async with self._limit:
            if self.stopped:
                return Result("unsent", detail=self.stopped)
            if self._remaining is not None:
                if self._remaining == 0:
                    self.stopped = "request budget used up"
                    return Result("unsent", detail=self.stopped)
                self._remaining -= 1
            self.sent += 1
            result = await self._send(state, questions)
        if result.status in ("scored", "unscored"):
            self._cache[key] = {k: v for k, v in asdict(result).items() if k != "cached"}
            with self._cache_path.open("a") as sink:
                sink.write(json.dumps({"key": key, "result": self._cache[key]}) + "\n")
        return result

    async def _send(self, state, questions) -> Result:
        body = {"model": MODEL, "state": state, "questions": questions}
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = await self._http.post(API, json=body)
            except httpx.TransportError as error:
                detail = "connection: " + type(error).__name__
            else:
                if response.status_code == 200:
                    return _parse(response, questions)
                detail = f"HTTP {response.status_code}"
                if response.status_code == 400 and "max_tokens_exceeded" in response.text:
                    return Result("unscored", detail="max_tokens_exceeded")
                if response.status_code in STOP_STATUS:
                    self.stopped = detail
                    return Result("error", detail=detail)
                if response.status_code not in RETRY_STATUS:
                    return Result("error", detail=detail)
            if attempt < ATTEMPTS:
                await asyncio.sleep(min(self._retry_delay * 2 ** (attempt - 1), 8))
        return Result("error", detail=detail)

    async def close(self):
        await self._http.aclose()


def api_key(env_file: Path = Path(".env")) -> str:
    if key := os.environ.get("TYPESAFE_API_KEY"):
        return key
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip()
    raise RuntimeError("TYPESAFE_API_KEY is not set (environment or .env)")


def _parse(response: httpx.Response, questions) -> Result:
    try:
        raw = response.json()
        scores = {name: raw["answers"][name]["noul"] for name in questions}
        if not all(type(s) in (int, float) and 0 <= s <= 1 for s in scores.values()):
            raise ValueError
        return Result("scored", scores, raw["model"], usage=raw.get("usage"))
    except (ValueError, KeyError, TypeError):
        return Result("error", detail="invalid response")


def _key(state, questions) -> str:
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return {row["key"]: row["result"] for row in map(json.loads, path.read_text().splitlines())}

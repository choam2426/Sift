"""Run directory: what was analysed, with which versions, and what came out."""

import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sift.code import Scan
from sift.triage import QUESTIONS, THRESHOLD, TOP_SHARE, Triaged, ranked
from sift.jev import MODEL


def manifest(target: Path) -> dict:
    return {
        "target": str(target.resolve()),
        "revision": _revision(target),
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": MODEL,
        "questions_sha256": hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode()).hexdigest(),
        "threshold": THRESHOLD,
        "top_share": TOP_SHARE,
    }


def write(directory: Path, manifest: dict, scan: Scan,
          triaged: list[Triaged], stopped: str | None) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    summary = _summary(scan, triaged, stopped)
    _json(directory / "manifest.json", manifest | {"configs": scan.configs, "summary": summary})
    _jsonl(directory / "functions.jsonl",
           [{k: v for k, v in asdict(f).items() if k != "code"} for f in scan.functions])
    _jsonl(directory / "unanalyzed.jsonl", [asdict(u) for u in scan.unanalyzed])
    _jsonl(directory / "triage.jsonl", [asdict(t) for t in triaged])
    _jsonl(directory / "selected.jsonl", [asdict(t) for t in ranked(triaged)])
    return summary


def _summary(scan, triaged, stopped) -> dict:
    status = Counter(t.status for t in triaged)
    return {
        "functions": len(scan.functions),
        "unanalyzed": dict(Counter(u.reason for u in scan.unanalyzed)),
        "parses": scan.parses, "failed_parses": scan.failed_parses,
        "error_diagnostics": scan.error_diagnostics,
        "scored": status["scored"], "unscored": status["unscored"],
        "error": status["error"], "unsent": status["unsent"],
        "selected": sum(t.selected for t in triaged),
        "input_tokens": sum(t.input_tokens for t in triaged),
        "stopped": stopped,
    }


def _revision(target: Path) -> str | None:
    done = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def _json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

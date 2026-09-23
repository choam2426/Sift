# 007 baseline-llm-judge

Status: done
Depends: 003

## Context

B2 arm: frontier judge on the labeled sample only (full scan too costly).

## Do

- Prompt frontier for a 0–1 "needs security review" score per function.
- Run on the 50-function sample; record cost + latency.
- Freeze the prompt before running (commit beside the code).

## Done when

- [x] Prompt frozen and committed.
- [x] 50 scores + cost/latency pasted in Notes.

## Notes

- 50/50 scored (2 retries: reasoning ate max_tokens twice; final 4096).
- Tokens ≈22.5k in / 86k out ≈ $0.02. Mean score 0.429. Per-row ms kept
  in `data/mastodon.llmjudge.jsonl`.
- Lesson: always-on reasoning needs 4k+ budget even for 1-number answers.

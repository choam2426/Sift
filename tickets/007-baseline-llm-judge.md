# 007 baseline-llm-judge

Status: open
Depends: 003

## Context

B2 arm: frontier judge on the labeled sample only (full scan too costly).

## Do

- Prompt frontier for a 0–1 "needs security review" score per function.
- Run on the 50-function sample; record cost + latency.
- Freeze the prompt before running (commit beside the code).

## Done when

- [ ] Prompt frozen and committed.
- [ ] 50 scores + cost/latency pasted in Notes.

# 005 baseline-rule

Status: done
Depends: 001

## Context

B1 arm: hand heuristic ranker. Jev must beat this to justify learned triage.

## Do

- Score functions by risky keywords/APIs + complexity signals.
  Keep the rule list short and committed beside the code.
- Run over the full Discourse set; rank the labeled sample.

## Done when

- [x] Rule list committed (frozen before seeing labels).
- [x] Ranked sample produced for the eval script (008).

## Notes

- 18 rules (6×w3/6×w2/6×w1) by blinded subagent (guide only).
  File-access audit clean. `eval/baselines/rule_list.json`.
- Full set scored: 2424/7181 nonzero (34%). `data/mastodon.rules.jsonl`.

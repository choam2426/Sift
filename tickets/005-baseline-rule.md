# 005 baseline-rule

Status: open
Depends: 001

## Context

B1 arm: hand heuristic ranker. Jev must beat this to justify learned triage.

## Do

- Score functions by risky keywords/APIs + complexity signals.
  Keep the rule list short and committed beside the code.
- Run over the full Discourse set; rank the labeled sample.

## Done when

- [ ] Rule list committed (frozen before seeing labels).
- [ ] Ranked sample produced for the eval script (008).

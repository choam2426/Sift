# 008 eval-report

Status: open
Depends: 004, 005, 006, 007

## Context

Head-to-head on the shared labeled sample ([eval.md](../docs/eval.md)).

## Do

- Eval script: recall@k / precision@k (k=5/10/20%) + band hit rates
  for arms B0/B1/B2/B3/Jev-noul/Jev-choice.
- Write `docs/specs/jev-eval-01.md` with the table + verdict vs the
  P0 success criteria.

## Done when

- [ ] One command reproduces the table from labels + arm outputs.
- [ ] Spec doc states pass/fail per success criterion.

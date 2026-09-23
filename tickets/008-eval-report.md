# 008 eval-report

Status: done
Depends: 004, 005, 006, 007

## Context

Head-to-head on the shared labeled sample ([eval.md](../docs/eval.md)).

## Do

- Eval script: recall@k / precision@k (k=5/10/20%) + band hit rates
  for arms B0/B1/B2/B3/Jev-noul/Jev-choice.
- Write `docs/specs/jev-eval-01.md` with the table + verdict vs the
  P0 success criteria.

## Done when

- [x] One command reproduces the table from labels + arm outputs.
- [x] Spec doc states pass/fail per success criterion.

## Notes

- `make eval` → [jev-eval-01.md](../docs/specs/jev-eval-01.md).
- Verdict: 필수 PASS / 목표 PASS++ / stretch PASS.
  P0 gate (track 1) cleared → expand to 3 tracks per D12.

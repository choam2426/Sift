# 004 labels

Status: open
Depends: 003

## Context

Human labels are the P0 ground truth ([eval.md](../docs/eval.md)).

## Do

- Write the label guide: positive = "analyst would spend 5+ min here"
  (auth decision, ownership/tenant check, state guard, sensitive sink).
  3 positive + 3 negative examples from the sample.
- Label the 50-function sample blind (no Jev scores visible).
- Record per label: `{function_id, label, one-line reason}`.

## Done when

- [ ] Guide committed next to labels.
- [ ] All 50 labels present with reasons.
- [ ] Positive rate + 2 borderline cases discussed in Notes.

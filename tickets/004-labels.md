# 004 labels

Status: done
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

- [x] Guide committed next to labels.
- [x] All 50 labels present with reasons.
- [x] Positive rate + 2 borderline cases discussed in Notes.

## Notes

- Labeled by isolated subagent (own context, blinded). File-access audit:
  guide + review + labels template only, zero manifest/scores/data reads.
- Positive rate 21/50 (42%).
- Borderlines (→1 per recall rule): vote double-vote guard
  (`VoteValidator#poll_non_multiple_and_already_voted?`), push visibility
  (`Web::PushNotificationWorker#perform`), invite gate
  (`User#valid_invitation?`).

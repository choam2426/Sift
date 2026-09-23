# Labels

Committed ground truth per track. Small files; safe to commit.

- `<track>.guide.md` — labeling rules (write before labeling).
- `<track>.manifest.json` — sample ids + bands + weights (from `make sample`).
- `<track>.review.jsonl` — blinded code for labelers (NO scores inside).
- `<track>.labels.json` — the labels (0/1 + one-line reason).

Rule: labelers read guide + review only (D13). Scores live in `data/`
(gitignored) and must never leak into this directory.

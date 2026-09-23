# Eval inputs (committed)

- `labels/` — per-track ground truth: guide + manifest + blinded review
  + labels. See [labels/README.md](labels/README.md).
- `baselines/` — frozen artifacts: rule list, judge prompt.
  See [baselines/README.md](baselines/README.md).

Regenerable outputs (scores, findings) live in `data/` (gitignored),
never here.

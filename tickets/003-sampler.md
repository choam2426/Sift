# 003 sampler

Status: open
Depends: 002

## Context

Labeling budget is ~50/track. Sample must cover all score bands so the
ranking curve (not just the top) is measurable.

## Do

- Stratified sample over Jev score bands (top 5% / 5–20% / 20–50% / rest).
- Fixed seed; sample manifest `{function_id, band}` committed with labels.
- Scores hidden from labelers (separate files).

## Done when

- [ ] 50-function Discourse sample drawn and band counts pasted in Notes.
- [ ] Re-running with the same seed reproduces the manifest.

# 003 sampler

Status: done
Depends: 002

## Context

Labeling budget is ~50/track. Sample must cover all score bands so the
ranking curve (not just the top) is measurable.

## Do

- Stratified sample over Jev score bands (top 5% / 5–20% / 20–50% / rest).
- Fixed seed; sample manifest `{function_id, band}` committed with labels.
- Scores hidden from labelers (separate files).

## Done when

- [x] 50-function Mastodon sample drawn and band counts pasted in Notes.
- [x] Re-running with the same seed reproduces the manifest.

## Notes

- Stratified on noul-auth rank: pop=[360,1077,2154,3590], alloc=13/13/12/12.
- Seed 7, byte-reproducible. Review order shuffled (seed 8), no score leak.
- Files: eval/labels/mastodon.{manifest,review,labels}.json* (committed).

# 006 baseline-semgrep

Status: done
Depends: 001

## Context

B3 arm: off-the-shelf SAST as the "existing tool" rival.

## Do

- Run Semgrep security rulesets on the Discourse checkout (record version).
- Map findings to functions → per-function density/severity score.
- Rank the labeled sample.

## Done when

- [x] Ruleset + version recorded in Notes.
- [x] Ranked sample produced for the eval script (008).

## Notes

- semgrep 1.177.0 (isolated `.venv-semgrep`), config `p/ruby` (44 rules).
- 119 findings on app+lib → 116 functions hit (1.6%), 1 unmapped.
- Sparse by nature (OSS pack). `data/mastodon.semgrep.jsonl`.

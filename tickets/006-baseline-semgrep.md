# 006 baseline-semgrep

Status: open
Depends: 001

## Context

B3 arm: off-the-shelf SAST as the "existing tool" rival.

## Do

- Run Semgrep security rulesets on the Discourse checkout (record version).
- Map findings to functions → per-function density/severity score.
- Rank the labeled sample.

## Done when

- [ ] Ruleset + version recorded in Notes.
- [ ] Ranked sample produced for the eval script (008).

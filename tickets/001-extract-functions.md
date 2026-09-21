# 001 extract-functions

Status: ready
Depends: none

## Context

P0 needs every function of each target as Jev input units.
First track only: Discourse ([D9](../docs/decisions.md)). Other tracks reuse.

## Do

- Pin the target version (record repo + commit in Notes).
- Extract functions via tree-sitter → JSONL per function:
  `{id, file, name, start_line, end_line, code}` (+ decorator/signature shell).
- One command runs it end to end for a track.

## Done when

- [ ] Extraction command exists and runs on Discourse checkout.
- [ ] Function count + 3 sample rows pasted in Notes.
- [ ] Ids are stable across re-runs (same commit → same ids).

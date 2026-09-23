# 001 extract-functions

Status: done
Depends: none

## Context

P0 needs every function of each target as Jev input units.
First track only: Mastodon ([D9](../docs/decisions.md)). Other tracks reuse.

## Do

- Pin the target version (record repo + commit in Notes).
- Extract functions via tree-sitter → JSONL per function:
  `{id, file, name, start_line, end_line, code}` (+ decorator/signature shell).
- One command runs it end to end for a track.

## Done when

- [x] Extraction command exists and runs on Discourse checkout.
- [x] Function count + 3 sample rows pasted in Notes.
- [x] Ids are stable across re-runs (same commit → same ids).

## Notes

- Repo: mastodon/mastodon @ `398b542` (depth-1, 2026-09-21).
- Scope cut: `app/` + `lib/` only (1328 files). streaming/frontend/spec excluded.
- Result: files=1328 functions=7181 errors=0 sha=1404cd0670f3e05a.
  Two runs byte-identical (cmp clean).
- Samples: `IpBlockPolicy#destroy?`, `MediaAttachmentPolicy#download?`,
  `#show_status?` (policies/ 집중 확인).
- Env: .venv tree-sitter 0.26.0 (see requirements.txt). D6 exception:
  parser runtime is the documented "needed" case.

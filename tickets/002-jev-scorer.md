# 002 jev-scorer

Status: open
Depends: 001

## Context

Score every extracted function with Jev ([eval.md](../docs/eval.md) P0).
Rate limits unknown — discover and respect them.

## Do

- Runner reads function JSONL, calls Jev (noul + choice arms), writes scores.
- Concurrency with backoff; resume on partial runs.
- Record model id, latency stats, token usage.

## Done when

- [ ] Full Discourse function set scored for both arms.
- [ ] Latency/token summary pasted in Notes.
- [ ] Re-run resumes instead of restarting.

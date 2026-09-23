# 002 jev-scorer

Status: done
Depends: 001

## Context

Score every extracted function with Jev ([eval.md](../docs/eval.md) P0).
Rate limits unknown — discover and respect them.

## Do

- Runner reads function JSONL, calls Jev (noul + choice arms), writes scores.
- Concurrency with backoff; resume on partial runs.
- Record model id, latency stats, token usage.

## Done when

- [x] Full Mastodon function set scored for all three arms.
- [x] Latency/token summary pasted in Notes.
- [x] Re-run resumes instead of restarting.

## Notes

- 7181 funcs × 3 arms = 21543 rows; 21496 ok, 47 transient errs
  (HTTP 529/503 during API outage window). 0.2% excluded from frame.
- noul-auth: mean 0.102, >0.5 = 429 (6.0%).
- choice-auth: explicit 652 / auth_only 286 / absent 6230.
- noul-broad: mean 0.295, >0.5 = 1873 (26%).
- Latency med ~510ms all arms, p95 ~600ms healthy (49s spikes in outage).
- Tokens in ≈8.4M ≈ $0.35. Output free.
- Resume verified (7156/7181 todo on relaunch). `--retry-errors` added;
  529/408 added to retryable set.

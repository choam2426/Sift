# Baselines

Frozen eval artifacts. Never edit in place — version the file instead.

- `rule_list.json` — B1 regex rules (blinded author, see tickets/005).
- `llm_judge_prompt.md` — B2 prompt (frozen 2026-09-21).

Each file records the exact input its baseline arm ran with, so `make eval`
stays reproducible.

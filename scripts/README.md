# Scripts

P0 pipeline order:

```text
extract → jev_score → sample → (label, human/subagent) →
rule_score + semgrep_map + llm_judge → eval
```

Probes (one-off measurements): `smoke`, `jev_probe`, `jev_ablation`.

Run everything via make (`make help`). Only `extract.py` needs `.venv`
(tree-sitter); the rest are stdlib-only.

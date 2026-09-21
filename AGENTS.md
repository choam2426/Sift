# AGENTS.md

Falsify: repo in → ranked security findings out. Cheap Jev triage,
frontier LLM deep dive, falsification. See [docs/product.md](docs/product.md).

## Run

Commands live in the Makefile. Start with `make help`.

## Read before working

- Product (why, roadmap): [docs/product.md](docs/product.md)
- Pipeline design: [docs/architecture.md](docs/architecture.md)
- Baselines and metrics: [docs/eval.md](docs/eval.md)
- Past calls: [docs/decisions.md](docs/decisions.md) — log new ones here

## Write where it belongs

- Measurements: `docs/specs/<topic>.md`
- Literature/background: `docs/research/YYYY-MM-DD-<slug>.md`
- Work items: `tickets/` (see [tickets/README.md](tickets/README.md))

## Rules

- Scripts are stdlib-only (bash+curl, python3 stdlib). No new deps.
- Secrets stay in `.env` (gitignored). Never print them.
- Commit only when asked. Never push without being asked.

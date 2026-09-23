TRACK ?= mastodon
ROOT ?= targets/$(TRACK)
SCOPE ?= app lib
OUT ?= data/$(TRACK).functions.jsonl
ARM ?= noul-auth
WORKERS ?= 8
LIMIT ?= 0
SCORE_OUT ?= data/$(TRACK).scores.jsonl

SAMPLE_N ?= 50
SEED ?= 7
SAMPLE_ARM ?= noul-auth

.PHONY: help smoke probe ablation extract score venv sample eval semgrep-scan semgrep-map

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

smoke: ## Key check + minimal Jev/frontier calls
	./scripts/smoke.sh

probe: ## Jev spec probe (latency/calibration/limits)
	python3 scripts/jev_probe.py

ablation: ## Question-design ablation (noul vs choice vs decomp)
	python3 scripts/jev_ablation.py

extract: ## Extract functions (TRACK/ROOT/SCOPE/OUT overridable)
	.venv/bin/python scripts/extract.py --track $(TRACK) --root $(ROOT) --scope $(SCOPE) --out $(OUT)

score: ## Score functions with Jev (ARM/WORKERS/LIMIT overridable)
	python3 scripts/jev_score.py --in $(OUT) --out $(SCORE_OUT) --arm $(ARM) --workers $(WORKERS) --limit $(LIMIT)

venv: ## Sync project .venv with uv
	uv sync

SEMGREP ?= semgrep
SEMGREP_CONFIG ?= p/ruby
semgrep-scan: ## Scan track sources (ROOT/CONFIG overridable)
	SEMGREP_SEND_METRICS=off $(SEMGREP) scan --config $(SEMGREP_CONFIG) --json -o data/$(TRACK).semgrep.json $(ROOT)/app $(ROOT)/lib

semgrep-map: ## Map findings to functions
	python3 scripts/semgrep_map.py --in $(OUT) --out data/$(TRACK).semgrep.jsonl --findings data/$(TRACK).semgrep.json --root $(ROOT)

sample: ## Stratified sample for labeling
	python3 scripts/sample.py --track $(TRACK) --arm $(SAMPLE_ARM) --n $(SAMPLE_N) --seed $(SEED)

eval: ## Head-to-head eval on labeled sample
	python3 scripts/eval.py --track $(TRACK)

.PHONY: help smoke probe ablation

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

smoke: ## Key check + minimal Jev/frontier calls
	./scripts/smoke.sh

probe: ## Jev spec probe (latency/calibration/limits)
	python3 scripts/jev_probe.py

ablation: ## Question-design ablation (noul vs choice vs decomp)
	python3 scripts/jev_ablation.py

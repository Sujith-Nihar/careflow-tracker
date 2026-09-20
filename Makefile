# CareFlow Tracker — see docs/PROJECT_PLAN.md for phases, docs/HUMAN_SETUP.md for credentials.
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
# Prefer the 3.12 binary by name; otherwise whatever `python3` is, which the rule
# below checks is new enough. The package needs >= 3.12 (backend/pyproject.toml).
PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3 2>/dev/null)

help: ## list targets
	@grep -hE '^[a-z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

$(VENV)/bin/python:
	@test -n "$(PYTHON)" || { echo "no python3 on PATH; install Python 3.12 or newer"; exit 1; }
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' || \
		{ echo "$(PYTHON) is $$($(PYTHON) -V); this project needs 3.12 or newer"; exit 1; }
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -q --upgrade pip

setup: $(VENV)/bin/python ## install backend deps (dev extras included)
	$(PIP) install -q -e "backend[dev]"
	@echo "backend deps installed. Frontend: make ui-install. Real voice runs: make setup-evals."

setup-evals: $(VENV)/bin/python ## install Playwright and its Chromium, needed only by `make eval`
	$(PIP) install -q -e "backend[evals]"
	$(PY) -m playwright install chromium
	@echo "playwright and chromium installed; 'make eval' can now drive browser calls."

lint: ## static analysis over every Python source
	$(VENV)/bin/ruff check backend evals vogent scripts
	$(VENV)/bin/ruff format --check backend evals vogent scripts

format: ## apply formatting
	$(VENV)/bin/ruff format backend evals vogent scripts

typecheck-ui: ## typecheck the dashboard
	cd frontend && npx tsc --noEmit

test: ## run backend tests (db-marked tests skip without DATABASE_URL)
	$(PYTEST) backend -q

test-cov: ## run backend tests with coverage of the domain layer
	$(PYTEST) backend -q --cov=backend/app/domain --cov-report=term-missing

db-check: ## verify DATABASE_URL connectivity
	$(PY) scripts/db_check.py

vogent-check: ## verify VOGENT_API_KEY by listing agents (prints no secrets)
	$(PY) scripts/vogent_check.py

migrate: ## apply backend/migrations/*.sql to DATABASE_URL
	$(PY) scripts/migrate.py

migrate-test: ## apply migrations to the careflow_test schema
	$(PY) scripts/migrate.py --test-schema

reset-calls: ## delete all call and evaluation data, keep the practices
	$(PY) scripts/reset_calls.py

seed: ## create the synthetic organizations
	$(PY) scripts/seed.py

api: ## run the Flask API on FLASK_PORT (default 5055), reloading on change
	$(PY) -m flask --app backend/app:create_app run --port $${FLASK_PORT:-5055} --reload

api-restart: ## restart the background API so it picks up code changes
	@kill $$(lsof -ti:$${FLASK_PORT:-5055}) 2>/dev/null || true
	@sleep 1
	@nohup $(PY) -m flask --app backend/app:create_app run --port $${FLASK_PORT:-5055} > /tmp/careflow-api.log 2>&1 &
	@sleep 4 && curl -sf http://localhost:$${FLASK_PORT:-5055}/healthz && echo " api restarted"

tunnel: ## expose the local API on BACKEND_PUBLIC_URL so Vogent can reach it
	@set -a; . ./.env; set +a; \
	ngrok http $${FLASK_PORT:-5055} --url=$$BACKEND_PUBLIC_URL

replay: ## run scenarios through the backend without voice (needs `make api` running)
	$(PY) -m evals.runner.cli --artifacts artifacts/replay

eval: ## real Vogent voice runs: make eval VERSION=v2 [SCENARIOS=...] [STRATEGY=optimized]
	$(PY) -m evals.runner.voice_cli --version $${VERSION:-v2} \
		--strategy $${STRATEGY:-naive_voice} $${SCENARIOS:+--scenarios $$SCENARIOS}

ui: ## run the staff dashboard on :3000 (needs `make api`)
	@set -a; . ./.env; set +a; cd frontend && npx next dev -p 3000

ui-install: ## install frontend dependencies
	cd frontend && npm install

structural: ## cheap flow lint, no calls, no cost
	$(PY) -c "import sys; sys.path.insert(0,'evals'); from runner.structural import check; \
		[print(f'{v}: {\"PASS\" if check(v).passed else \"FAIL\"} ({len(check(v).findings)} findings)') for v in ('v1','v2')]"

tf-validate: ## check the AWS definition is valid (no account needed)
	cd infra/terraform && terraform init -backend=false -input=false >/dev/null && terraform fmt -check && terraform validate

worker-demo: ## async path end to end: success, poisoned job, DLQ, log correlation
	@scripts/worker_demo.sh

secret-scan: ## fail if anything that looks like a credential is tracked by git
	@scripts/secret_scan.sh

.PHONY: help setup setup-evals lint format typecheck-ui test test-cov db-check vogent-check migrate migrate-test reset-calls seed api api-restart tunnel replay eval structural ui ui-install worker-demo tf-validate secret-scan

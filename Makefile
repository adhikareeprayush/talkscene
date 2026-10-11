SHELL := /bin/bash
API := apps/api
PY  := $(API)/.venv/bin/python
PIP := $(API)/.venv/bin/pip

.PHONY: help setup api web dev openapi sdk scenarios test test-api test-e2e lint fmt migrate seed clean docker

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Create the API venv, install everything, install web deps
	python3 -m venv $(API)/.venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "$(API)[dev]"
	@command -v pnpm >/dev/null && pnpm install || echo "pnpm not found - skipping web deps"
	@test -f .env || cp .env.example .env
	@echo "✓ setup complete - run 'make api' and 'make web'"

api: ## Run the FastAPI server on :8000
	cd $(API) && .venv/bin/uvicorn talkscene.main:app --reload --port 8000

web: ## Run the Next.js PWA on :3000
	pnpm --filter @talkscene/web dev

openapi: ## Export the OpenAPI contract to docs/openapi.yaml
	$(PY) -m talkscene.cli export-openapi ../../docs/openapi.yaml

sdk: openapi ## Regenerate the TypeScript SDK from the contract
	pnpm gen:sdk

scenarios: ## Validate every scenario pack against the JSON schema
	$(PY) -m talkscene.cli validate-scenarios

test: test-api ## Run the full test suite

test-api: ## Run backend tests
	cd $(API) && .venv/bin/pytest -q

test-e2e: ## Run Playwright E2E against mock providers
	pnpm test:e2e

lint: ## Ruff + mypy + eslint
	cd $(API) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy talkscene
	@command -v pnpm >/dev/null && pnpm lint || true

fmt: ## Autoformat
	cd $(API) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

migrate: ## Apply database migrations
	cd $(API) && .venv/bin/alembic upgrade head

seed: ## Load scenario packs into the database
	$(PY) -m talkscene.cli seed

docker: ## Bring up the whole stack (postgres, redis, api, web)
	docker compose -f infra/docker-compose.yml up --build

clean:
	rm -rf $(API)/.venv var apps/web/.next node_modules

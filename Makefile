# Groundplan: local-only dev targets. Postgres 17 on the /tmp socket, current OS user, no password.
SHELL := /bin/bash
PGHOST ?= /tmp
BACKEND := backend
API_PORT ?= 8000

.PHONY: help db db-reset api seed migrate migrations-sql openapi fixtures lint web pipeline-eval pipeline-service synth test test-backend test-pipeline test-web go-test parity

help:
	@echo "make db            create groundplan_dev + groundplan_test (if missing), migrate dev, load the demo household"
	@echo "make api           run the FastAPI app on :$(API_PORT) (OpenAPI at /docs)"
	@echo "make web           run the Vite dev server on :5173 (proxies /api to :$(API_PORT))"
	@echo "make pipeline-eval run the document pipeline eval -> fixtures/documents/eval-latest.json"
	@echo "make test          pytest (backend + pipeline), vitest (web), go test (engine-go) -- each skipped if absent"
	@echo "make go-test       go test ./... in engine-go"
	@echo "make fixtures      regenerate fixtures/engine/*.json (asserts the hand-checked values)"
	@echo "make openapi       write backend/openapi.json (THE API contract for engine-go and web)"
	@echo "make migrations-sql write backend/migrations.sql (offline Alembic SQL the Go service ships)"
	@echo "make synth         regenerate the synthetic documents into fixtures/documents"
	@echo "make pipeline-service run the gp-pipeline HTTP service on :8090"
	@echo "make parity A=<base> B=<base>  diff the two backends (scripts/parity.py)"

db:
	@for d in groundplan_dev groundplan_test; do \
	  psql -h $(PGHOST) -d postgres -Atc "select 1 from pg_database where datname='$$d'" | grep -q 1 || createdb -h $(PGHOST) $$d; \
	done
	cd $(BACKEND) && uv sync -q && uv run alembic upgrade head && uv run python -m scripts.seed

db-reset:
	psql -h $(PGHOST) -d groundplan_dev -qc "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	$(MAKE) db

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

seed:
	cd $(BACKEND) && uv run python -m scripts.seed

api:
	cd $(BACKEND) && uv run uvicorn groundplan.api:app --reload --port $(API_PORT)

openapi:
	cd $(BACKEND) && uv run python -c "import json; from groundplan.api import app; print(json.dumps(app.openapi(), indent=2))" > openapi.json
	@echo "wrote $(BACKEND)/openapi.json"

migrations-sql:
	cd $(BACKEND) && uv run alembic upgrade head --sql 2>/dev/null > migrations.sql
	@echo "wrote $(BACKEND)/migrations.sql"

synth:
	cd pipeline && uv run python -m gp_pipeline.synth --out ../fixtures/documents

pipeline-service:
	cd pipeline && uv run uvicorn gp_pipeline.service:app --port 8090

parity:
	uv run --no-project --with httpx python scripts/parity.py $(A) $(B)

fixtures:
	cd $(BACKEND) && uv run python -m scripts.gen_fixtures

lint:
	cd $(BACKEND) && uv run ruff check .

web:
	@if [ -d web ]; then cd web && npm run dev; else echo "web/ not present yet"; exit 1; fi

pipeline-eval:
	@if [ -d pipeline ]; then cd pipeline && uv run python -m gp_pipeline.eval --docs ../fixtures/documents --out ../fixtures/documents/eval-latest.json; \
	else echo "pipeline/ not present yet"; exit 1; fi

test: test-backend test-pipeline test-web go-test

test-backend:
	cd $(BACKEND) && uv run ruff check . && uv run pytest -q

test-pipeline:
	@if [ -d pipeline ]; then cd pipeline && uv run pytest -q; else echo "skip: pipeline/ not present"; fi

test-web:
	@if [ -f web/package.json ]; then cd web && npx vitest run; else echo "skip: web/ not present"; fi

go-test:
	@if [ -f engine-go/go.mod ]; then cd engine-go && go test ./...; else echo "skip: engine-go/ not present"; fi

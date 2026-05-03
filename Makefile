.PHONY: db db-stop db-reset schema migrate-sqlite api monitor scrape scheduler test

# ── Local Postgres ────────────────────────────────────────────────────────────

db:
	docker-compose up db -d

db-stop:
	docker-compose down

db-reset:
	docker-compose down -v
	docker-compose up db -d

pgadmin:
	docker-compose up pgadmin -d

# ── Schema ────────────────────────────────────────────────────────────────────

schema:
	@export $$(cat .env | grep -v '^#' | xargs) && \
	  .venv/bin/python -c "from eventtrace.config import Settings; from eventtrace.db import get_db; db = get_db(Settings()); db.ensure_schema(); print('schema OK')"

# ── Migrate existing SQLite data to Postgres ──────────────────────────────────

migrate-sqlite:
	@echo "Re-scrape today to populate Postgres:"
	@echo "  make scrape DATE=2026-04-30"

# ── Dev servers ───────────────────────────────────────────────────────────────

api:
	@export $$(cat .env | grep -v '^#' | xargs) && .venv/bin/chd-api

monitor:
	@export $$(cat .env | grep -v '^#' | xargs) && .venv/bin/chd-run-monitor

# ── Causelist scraper ─────────────────────────────────────────────────────────

scrape:
	@export $$(cat .env | grep -v '^#' | xargs) && \
	  .venv/bin/chd-scrape-causelist $(DATE) --store

scheduler:
	@export $$(cat .env | grep -v '^#' | xargs) && .venv/bin/chd-schedule-causelist

test:
	@python -m unittest discover -s tests -q

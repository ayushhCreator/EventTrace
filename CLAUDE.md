# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install
```

## Commands

| Task | Command |
|------|---------|
| Start monitor loop | `chd-run-monitor` |
| Start API | `chd-api` |
| Start causelist scheduler | `chd-schedule-causelist` |
| Init session (only if JSON stops working) | `chd-init-session` |
| Scrape causelist (one-shot) | `chd-scrape-causelist YYYY-MM-DD --store` |
| Lint | `ruff check src/` |
| Format | `ruff format src/` |

Run all three together locally (3 terminals): `chd-api` + `chd-run-monitor` + `chd-schedule-causelist`.

API runs at `http://127.0.0.1:8009` by default. Override with `CHD_API_HOST` / `CHD_API_PORT`.
Legacy embedded UI at `http://127.0.0.1:8009/ui` (do NOT edit unless explicitly told).

## Frontend (new UI)

The real UI is a separate React/TypeScript/Tailwind app at `/home/ayush-raj/The_Base/EventTrace-Web`.
**All UI changes go there unless the user explicitly says to edit the old `src/eventtrace/ui/` files.**

| Task | Command |
|------|---------|
| Dev server | `cd /home/ayush-raj/The_Base/EventTrace-Web && npm run dev` |
| Build | `npm run build` |

Key files:
- `src/api/client.ts` — all API calls
- `src/pages/Causelist.tsx` — cause list browser
- `src/pages/CauselistSearch.tsx` — case search
- `src/pages/DisplayBoard.tsx` — real-time monitor

## Local Postgres (Docker)

```bash
make db          # start Postgres on :5432
make schema      # create all tables in Postgres
make pgadmin     # pgAdmin UI at http://localhost:5050 (admin@local.dev / admin)
make db-stop     # stop containers
make db-reset    # wipe and restart (destroys data)
```

Set `DATABASE_URL` in `.env` (already configured for Docker). Leave empty to fall back to SQLite.

## Architecture

Two DB backends, same code:
- `DATABASE_URL` set → `PostgresDB` (psycopg2, connection pool)
- `DATABASE_URL` empty → `DB` (SQLite WAL, file-based)

`get_db(settings)` in `db.py` picks the right one. All five processes use `get_db()`.

Four independent processes share the DB:

```
init_session          →  .state/storage_state.json   (one-time manual CAPTCHA)
run_monitor           →  scraper → change_detector → DB  (poll loop, ~15s)
schedule_causelist    →  causelist PDF → causelist_case/bench tables (daily, 20:30–22:00 IST)
api                   →  DB reads only (FastAPI, read-only)
```

**Data flow in the monitor loop** (`run_monitor.py`):
1. `scraper.scrape_table_once_sync` — Playwright navigates to `principal.php`, fetches `display_api.json` via in-page JS (bypasses CAPTCHA; endpoint is public), returns `list[dict]`
2. `_build_court_id` — joins `CHD_KEY_FIELDS` columns (default: `court_no`) into a stable string key
4. `change_detector.apply_snapshot` — compares snapshot against `field_state` table; emits `EventTrace` records for changed fields; also tracks court presence via synthetic `__present__` field

**DB schema** (`db.py`):
- `current_state` — latest full row per court (JSON blob)
- `field_state` — current value + `start_time` per (court, field); acts as the "previous snapshot"
- `event_trace` — append-only change log with `duration_seconds` computed at write time

**API endpoints** (`api.py`):
- `GET /current-state` — all courts, latest data
- `GET /event-traces` — change log (alias: `/changes`), filterable by `court_id`
- `GET /field-state/{court_id}` — per-field history for one court
- `GET /causelist/dates` — dates with stored cause lists
- `GET /causelist/prefixes` — distinct case-ref type prefixes (MAT, FMA…)
- `GET /causelist/search` — search cases by `case_ref`, `advocate`, `party`, `judge`, `date_from`, `date_to`
- `GET /causelist/{YYYY-MM-DD}` — all benches for a date
- `POST /auth/send-otp` — send OTP to phone (MSG91 in prod, logged in dev)
- `POST /auth/verify-otp` — verify OTP, returns JWT
- `GET /auth/me` — current user (requires Bearer token)

## Key design decisions

- Headers are detected dynamically each scrape — never hardcode column names.
- `field_state.start_time` tracks when the *current* value was first seen; `duration_seconds` in `event_trace` is computed as `end_time - start_time` at the moment a change is written.
- Session cookies are persisted to `.state/storage_state.json` to survive the CAPTCHA across monitor restarts. Re-run `chd-init-session` if the site blocks the session.
- `CHD_KEY_FIELDS` can be comma-separated for composite keys.

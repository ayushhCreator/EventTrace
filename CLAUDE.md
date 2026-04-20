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
| Init session (only if JSON stops working) | `chd-init-session` |
| Lint | `ruff check src/` |
| Format | `ruff format src/` |

API runs at `http://127.0.0.1:8009` by default. Override with `CHD_API_HOST` / `CHD_API_PORT`.
UI at `http://127.0.0.1:8009/ui`.

## Architecture

Three independent processes share a single SQLite DB (`eventtrace.sqlite3`, WAL mode):

```
init_session  →  .state/storage_state.json   (one-time manual CAPTCHA)
run_monitor   →  scraper → change_detector → DB  (poll loop)
api           →  DB reads only (FastAPI, read-only)
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

## Key design decisions

- Headers are detected dynamically each scrape — never hardcode column names.
- `field_state.start_time` tracks when the *current* value was first seen; `duration_seconds` in `event_trace` is computed as `end_time - start_time` at the moment a change is written.
- Session cookies are persisted to `.state/storage_state.json` to survive the CAPTCHA across monitor restarts. Re-run `chd-init-session` if the site blocks the session.
- `CHD_KEY_FIELDS` can be comma-separated for composite keys.

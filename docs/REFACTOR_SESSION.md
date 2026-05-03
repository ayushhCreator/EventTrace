# Refactor Session Summary (EventTrace)

Date: 2026-05-02

This document summarizes the refactor work performed in this session to move the codebase toward cleaner, more production-grade structure (SOLID/DRY/SoC) while preserving existing behavior and entrypoints.

## Goals

- Reduce large single-file modules by splitting into focused packages.
- Improve separation of concerns: HTTP transport vs services vs storage vs domain.
- Remove obvious DRY violations.
- Preserve backward compatibility (same CLI scripts, same API routes, same imports).
- Add minimal automated verification (unit test + compile checks).

## High-level changes

### 1) Extracted pure domain and shared time utilities

- Added `src/eventtrace/domain/models.py` containing the `EventTrace` dataclass (domain object).
- Added `src/eventtrace/common/time.py` containing:
  - `utc_now()`, `iso()`, `parse_iso()`
  - Central IST helpers: `IST`, `ist_now()`, `ist_today_date()`, `ist_today_str()`
- Updated `src/eventtrace/change_detector.py` (and later the moved module under `monitor/`) to import `EventTrace` and time helpers from these modules instead of defining them in the DB layer.

Why:
- Keeps domain objects and time parsing/formatting side-effect free and reusable.
- Reduces coupling between change detection and persistence.

### 2) Introduced minimal unit test coverage

- Added `tests/test_change_detector.py` to validate `apply_snapshot()` behavior:
  - Creates a temporary SQLite DB
  - Applies two snapshots
  - Verifies an `event_trace` record is written for a field change
- Added `make test` in `Makefile`.
- Documented `make test` in `README.md`.

Why:
- Establishes a baseline safety net for refactors.

### 3) Split storage backends out of `db.py`

Original situation:
- `src/eventtrace/db.py` was a very large “god module” containing:
  - SQLite DB implementation
  - Postgres implementation
  - Schema / migrations
  - Subscriptions, causelist persistence, auth tables/queries, etc.

Changes:
- Created `src/eventtrace/storage/sqlite.py` containing the SQLite `DB` implementation.
- Created `src/eventtrace/storage/postgres.py` containing `PostgresDB`.
- Rewrote `src/eventtrace/db.py` into a thin facade:
  - Re-exports `DB`/`PostgresDB`
  - Keeps `get_db(settings)` behavior stable (selects Postgres if `DATABASE_URL` is set, otherwise SQLite).

Why:
- Improves separation of concerns and makes future refactors safer.
- Keeps the public “DB factory” stable to avoid breaking callers.

## API refactor: from one big module to routers + schemas + services

### 4) Split FastAPI routes into routers

Original situation:
- `src/eventtrace/api.py` contained:
  - App creation
  - All routes (health, current-state, history, exports)
  - OTP/JWT auth
  - Alert creation endpoint
  - Twilio webhook verification + handler
  - UI HTML serving
  - Many helpers/validators

Changes:
- Replaced `src/eventtrace/api.py` with a thin app factory that:
  - Creates `Settings`, initializes DB, calls `ensure_schema()`
  - Stores `settings` and `db` in `app.state`
  - Includes routers
  - Keeps `main()` entrypoint stable
- Added routers in `src/eventtrace/routes/`:
  - `health.py` (`/health`)
  - `display.py` (`/current-state`, `/vc-links*`, `/changes`/`/event-traces`, `/field-state`, `/absent-courts`, `/field-durations`)
  - `history.py` (`/history/*`)
  - `export.py` (`/export/*`)
  - `alerts.py` (`/alert`)
  - `webhooks.py` (`/webhook/whatsapp`)
  - `causelist.py` (`/causelist/*`)
  - `auth.py` (`/auth/*`)
  - `ui.py` (`/`, `/ui`, `/admin`)
  - `utils.py` (router-level helpers)

Why:
- Each router has a single responsibility (HTTP transport only).
- Makes endpoints easier to reason about and test.

### 5) Extracted request models (Pydantic) and service helpers

Added schemas:
- `src/eventtrace/schemas/auth.py`:
  - `SendOTPRequest`, `VerifyOTPRequest`, `UpdateProfileRequest`
  - Phone normalization via Pydantic validators (v1/v2 compatible).
- `src/eventtrace/schemas/alerts.py`:
  - `AlertRequest` with:
    - `hearing_date` format validation
    - `contact_type` validation
    - WhatsApp requires `phone` (cross-field validation with v1/v2 fallback)

Added services:
- `src/eventtrace/services/auth.py`: OTP/JWT helpers and MSG91 integration.
- `src/eventtrace/services/csv_export.py`: shared CSV streaming response helper.
- `src/eventtrace/services/validators.py`: shared date/UTC parsing helpers.
- `src/eventtrace/services/twilio.py`: Twilio signature verification helper.
- `src/eventtrace/services/deps.py`: `get_settings` / `get_db` dependencies using `app.state`.

Why:
- Validation/normalization lives near the schema instead of duplicated in handlers.
- Service modules are easier to test than route handlers.
- Router modules become thin and readable.

## Project structure refactor: moving remaining top-level modules into folders

### 6) Moved long top-level modules into subpackages + added shims

To reduce clutter in `src/eventtrace/`, the following packages were created:

- `src/eventtrace/core/` (configuration)
- `src/eventtrace/monitor/` (monitor loop, change detection)
- `src/eventtrace/scraping/` (scraper + Playwright init session)
- `src/eventtrace/bots/` (Telegram + WhatsApp)
- `src/eventtrace/causelist/` (scraper/parser/scheduler/backfill)
- `src/eventtrace/common/normalize.py` (moved normalize helpers)

The original top-level modules were replaced with backward-compatible shims that re-export everything from the new locations, so existing imports and `pyproject.toml` scripts continue to work:

- `src/eventtrace/config.py` → `eventtrace.core.config`
- `src/eventtrace/run_monitor.py` → `eventtrace.monitor.run_monitor`
- `src/eventtrace/change_detector.py` → `eventtrace.monitor.change_detector`
- `src/eventtrace/scraper.py` → `eventtrace.scraping.scraper`
- `src/eventtrace/init_session.py` → `eventtrace.scraping.init_session`
- `src/eventtrace/telegram_bot.py` → `eventtrace.bots.telegram_bot`
- `src/eventtrace/whatsapp_bot.py` → `eventtrace.bots.whatsapp_bot`
- `src/eventtrace/causelist_parser.py` → `eventtrace.causelist.causelist_parser`
- `src/eventtrace/causelist_scraper.py` → `eventtrace.causelist.causelist_scraper`
- `src/eventtrace/causelist_scheduler.py` → `eventtrace.causelist.causelist_scheduler`
- `src/eventtrace/backfill.py` → `eventtrace.causelist.backfill`
- `src/eventtrace/normalize.py` → `eventtrace.common.normalize`

Additionally:
- Updated moved modules’ relative imports to use `..` as needed.
- Fixed a missing import introduced by the move in `src/eventtrace/monitor/run_monitor.py`.
- Updated `.env` auto-loading path inside `src/eventtrace/core/config.py` so it still loads the project root `.env`.

Why:
- Cleaner, scalable layout without breaking existing behavior.
- Lets future work split modules further (e.g., separate repos per domain).

## DRY improvements performed

- Centralized IST date/time helpers in `src/eventtrace/common/time.py` and reused across API, bots, monitor, scheduler.
- Reduced duplication for CSV export + OTP date parsing and validation by moving them into service helpers.

## Backward compatibility notes

- **Console scripts** in `pyproject.toml` still point to the original module paths, and continue to work because shims keep those modules importable.
- **API endpoints** remain the same paths as before; only internal organization changed.
- **DB factory** `eventtrace.db.get_db(Settings())` remains stable.

## Verification run during the session

These were run successfully after refactors:

- `python -m compileall -q src/eventtrace scripts`
- `python -m unittest discover -s tests -q`

## Known follow-ups (not done yet)

- Further split `storage/sqlite.py` and `storage/postgres.py` into per-domain repositories:
  - `repositories/events.py`, `repositories/subscriptions.py`, `repositories/causelist.py`, `repositories/auth.py`
- Add more unit tests:
  - OTP expiry/rate limit behavior
  - Subscription creation + notification logic
  - Causelist parsing edge cases
- Consider tightening CORS in production deployments (currently `allow_origins=["*"]`).
- Ensure `JWT_SECRET` is required in production environments (avoid insecure defaults).


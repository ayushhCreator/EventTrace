# Dev Session — 30 April 2026
## PostgreSQL Migration + Docker Setup

**Date:** 2026-04-30  
**Status:** Complete — ready to test

---

## What Was Done

### 1. PostgreSQL Backend (`db.py`)

Added `PostgresDB` class — a complete drop-in replacement for the existing `DB` (SQLite) class.
Same public interface. Every method reimplemented with psycopg2 syntax.

Key differences from SQLite:
- `?` placeholders → `%s`
- `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
- `con.execute()` → cursor via `ThreadedConnectionPool`
- `RETURNING id` to get inserted row ID instead of `lastrowid`
- `DATE(observed_time, '+5 hours', '30 minutes')` → `(observed_time::timestamptz AT TIME ZONE 'Asia/Kolkata')::date`
- `GROUP_CONCAT` → `string_agg`
- `ILIKE` instead of `LIKE` for case-insensitive search

**Connection pool:** `psycopg2.pool.ThreadedConnectionPool(1, 5, dsn)` — lazy init (pool created on first query, not on import). This means the app starts cleanly even if the DB is temporarily unreachable.

**Trigram indexes:** `ensure_schema()` attempts to enable `pg_trgm` extension and create GIN indexes on `advocate`, `petitioner`, `respondent` columns. Non-fatal if the extension is unavailable (e.g. restricted Supabase plan).

### 2. Factory Function (`db.py`)

```python
def get_db(settings) -> DB | PostgresDB:
    if settings.database_url:
        return PostgresDB(settings.database_url)
    return DB(settings.db_path)
```

All five processes now call `get_db(settings)` instead of `DB(settings.db_path)`.
Zero changes to calling code beyond the import swap.

Files updated:
- `api.py`
- `run_monitor.py`
- `telegram_bot.py`
- `causelist_scraper.py`
- `causelist_parser.py`

### 3. `store_causelist()` moved into DB classes

The old `upsert_causelist()` in `causelist_parser.py` used `db.connect()` directly (SQLite-specific).
Moved the SQL into `DB.store_causelist()` and `PostgresDB.store_causelist()` with backend-appropriate syntax.
`causelist_parser.upsert_causelist()` is now a one-line delegate: `return db.store_causelist(parsed, scraped_at)`.

### 4. `.env` auto-loading (`config.py`)

Added `python-dotenv` — `config.py` now auto-loads `.env` from the project root on import.
`override=False` so shell-exported vars take precedence over `.env`.

```python
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)
```

### 5. `DATABASE_URL` in `Settings`

```python
self.database_url = _get_env("DATABASE_URL", "") or None
```

Set this to a PostgreSQL DSN → all processes use Postgres.
Leave empty → fall back to SQLite (local dev without Docker).

### 6. Docker Compose (`docker-compose.yml`)

```yaml
services:
  db:          # postgres:16-alpine on :5432
  pgadmin:     # pgAdmin4 on :5050
```

`pgdata` volume persists data across container restarts.
Health check on `pg_isready` — other services wait until Postgres is accepting connections.

### 7. `Makefile`

Common commands:
```bash
make db          # docker compose up db -d
make schema      # run ensure_schema() against configured DB
make scrape DATE=2026-04-30  # scrape + store causelist
make api         # start FastAPI with .env loaded
make monitor     # start monitor loop with .env loaded
```

---

## Why This Matters

**SQLite cannot be used in production.** The backend runs on Railway (or Render). The frontend runs on Vercel. They are on different servers. SQLite is a local file — there is no way for Railway to share a `.sqlite3` file with the monitor process running elsewhere.

PostgreSQL is a network database. Any process anywhere can connect to it with a DSN string. This enables:

| Capability | SQLite | PostgreSQL |
|---|---|---|
| Multiple processes on different machines | ❌ | ✅ |
| Frontend (Vercel) → API (Railway) → shared DB | ❌ | ✅ |
| Full-text search (tsvector) | ❌ | ✅ |
| Trigram fuzzy name matching (pg_trgm) | ❌ | ✅ |
| Array columns (`TEXT[]`) | ❌ | ✅ |
| Managed hosting with backups (Supabase) | N/A | ✅ |

**The SQLite fallback is preserved.** Without `DATABASE_URL` set, everything works exactly as before. No breakage for existing local dev.

---

## Dependencies Added

| Package | Version | Purpose |
|---|---|---|
| `psycopg2-binary` | `>=2.9` | PostgreSQL driver |
| `python-dotenv` | `>=1.0` | Auto-load `.env` file |

---

## What To Do Next

### Step 1 — Test local Postgres (now)
```bash
# Container should already be running
docker compose ps

# Create schema in Postgres
make schema

# Scrape today's causelist into Postgres
make scrape DATE=2026-04-30

# Start API (reads from Postgres)
make api

# Verify
curl http://127.0.0.1:8009/causelist/2026-04-30 | python3 -m json.tool | head -30
```

### Step 2 — Supabase (production DB)

1. Go to [supabase.com](https://supabase.com) → New Project → name: `eventtrace`
2. Settings → Database → Connection String → URI mode → copy
3. Paste into `.env` as `DATABASE_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres`
4. Run `make schema` — creates all tables in Supabase
5. Run `make scrape DATE=2026-04-30` — loads data into Supabase

### Step 3 — Railway deploy (backend)

1. Connect GitHub repo to Railway
2. Add env vars (copy from `.env`): `DATABASE_URL`, `TELEGRAM_TOKEN`, `TWILIO_*`
3. Set start command: `chd-api`
4. Railway gives you a public URL: `https://eventtrace.up.railway.app`

### Step 4 — Frontend (React + Vite)

After Railway URL is stable:
```bash
mkdir frontend && cd frontend
npm create vite@latest . -- --template react-ts
npm install @tanstack/react-query tailwindcss
```

Build the search UI per `SYSTEM_ARCHITECTURE_PROPOSAL.md` section 2.

### Step 5 — Vercel deploy (frontend)

Connect `frontend/` subdirectory to Vercel.
Set `VITE_API_URL=https://eventtrace.up.railway.app`.

---

## Architecture State After This Session

```
.env (DATABASE_URL set)
        │
        ▼
config.py → Settings.database_url
        │
        ▼
get_db(settings)
        ├── PostgresDB  ← if DATABASE_URL set  → Docker local / Supabase prod
        └── DB (SQLite) ← if DATABASE_URL empty → ./data/eventtrace.sqlite3
```

All five processes (api, monitor, bot, causelist_scraper, causelist_parser) go through `get_db()`.

---

## Files Changed This Session

| File | Change |
|---|---|
| `src/eventtrace/db.py` | Added `PostgresDB`, `store_causelist()` on both backends, `get_db()` factory |
| `src/eventtrace/config.py` | Added `database_url`, `python-dotenv` auto-load |
| `src/eventtrace/api.py` | `DB(...)` → `get_db(settings)` |
| `src/eventtrace/run_monitor.py` | `DB(...)` → `get_db(settings)`, removed stale `DB` type annotations |
| `src/eventtrace/telegram_bot.py` | `DB(...)` → `get_db(settings)` |
| `src/eventtrace/causelist_scraper.py` | `DB(...)` → `get_db(settings)` |
| `src/eventtrace/causelist_parser.py` | `upsert_causelist()` delegates to `db.store_causelist()` |
| `pyproject.toml` | Added `psycopg2-binary>=2.9`, `python-dotenv>=1.0` |
| `docker-compose.yml` | New — Postgres 16 + pgAdmin |
| `Makefile` | New — `make db`, `make schema`, `make scrape`, `make api` |
| `.env` | Added `DATABASE_URL` for local Docker |
| `.env.example` | Updated with full env var reference |
| `CLAUDE.md` | Updated commands table + Docker section |

# Migration & Causelist Research

## 1. SQLite → PostgreSQL

### Why Postgres Makes Sense Now

SQLite + WAL works fine for a single-machine read/write loop. Switch to Postgres when:
- Frontend is a separate process (Docker container, Vercel edge, etc.) — they can't share a file
- You want concurrent writers (monitor + future ingest jobs)
- You want `pg_notify` / LISTEN-NOTIFY for real-time pushes to frontend

### Migration Path

**Step 1 — Swap the `DB` class.**  
Replace `sqlite3` with `psycopg2` (sync) or `asyncpg` (async). The SQL is almost identical:

| SQLite idiom | Postgres equivalent |
|---|---|
| `?` placeholder | `%s` (psycopg2) or `$1` (asyncpg) |
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` or `BIGSERIAL` |
| `ON CONFLICT(...) DO UPDATE` | identical — Postgres invented it |
| `PRAGMA journal_mode=WAL` | drop — Postgres handles this |
| `sqlite_master` | `information_schema.tables` |
| `DATE(ts, '+5 hours', '30 minutes')` | `(ts AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Kolkata'` |

**Step 2 — Schema migration tool.**  
Use **Alembic** (de-facto standard for SQLAlchemy projects) or plain SQL migration files.  
For this project's size, plain numbered SQL files (`migrations/001_init.sql`) in a `migrations/` dir is sufficient. Run them once on deploy.

**Step 3 — Connection string via env var.**  
```
DATABASE_URL=postgresql://user:pass@localhost:5432/eventtrace
```
Config already uses `Settings` (pydantic-settings / dataclass) — add `db_url` field, keep `db_path` for local dev fallback.

**Step 4 — Data migration.**  
```bash
# Dump SQLite to SQL, reload into Postgres
sqlite3 eventtrace.sqlite3 .dump | grep -v "^CREATE\|^INSERT INTO sqlite" > dump.sql
# Edit CREATE TABLE statements to Postgres syntax, then:
psql $DATABASE_URL < dump.sql
```
Or use `pgloader` (one command, handles type mapping automatically):
```bash
pgloader sqlite:///eventtrace.sqlite3 postgresql://user:pass@localhost/eventtrace
```

### Recommended DB: **PostgreSQL 16**

- `LISTEN/NOTIFY` → push live court changes to frontend WebSocket without polling
- `JSONB` for `current_state.data_json` → index individual fields, query inside JSON
- Row-level security for multi-tenant future
- Supabase (managed Postgres) = free tier, built-in REST + realtime, no infra to manage

---

## 2. Frontend / Backend Split

### Current state
Everything is one Python process: FastAPI serves the UI as static HTML + a `/ui` route. No JS framework.

### Recommended Split

```
backend/    ← existing FastAPI (Python)
frontend/   ← React + Vite (new)
```

**Backend stays as-is**, just:
- Add CORS headers (`fastapi.middleware.cors.CORSMiddleware`, allow frontend origin)
- Optionally add WebSocket endpoint for live push (replaces polling)
- Keep all DB writes in the monitor process, never in the frontend

**Frontend tech stack recommendation: React + Vite + TailwindCSS**

| Layer | Choice | Reason |
|---|---|---|
| Framework | **React 18** | Ecosystem, hooks, easiest to hire for |
| Build | **Vite** | Fast HMR, tiny config, works with React |
| Styling | **Tailwind CSS v4** | Utility-first, no runtime cost |
| Data fetching | **TanStack Query (React Query)** | Automatic refetch, stale-while-revalidate, loading/error states |
| Routing | **React Router v6** | SPA routing |
| Tables | **TanStack Table** | Virtualized, sortable, filterable — important for long causelists |
| Realtime | **native WebSocket** or **@supabase/realtime** if using Supabase | Live court updates without polling |
| Deployment | **Vercel** (free) or static files served by Nginx | |

**Why not Next.js?** SSR adds complexity for a real-time dashboard. Pure SPA (Vite + React) is simpler and faster to build.

**Why not Vue/Svelte?** React has the widest ecosystem and most readily available legal-tech UI components.

### API contract (what backend needs to expose)

```
GET  /current-state          ← court board (already exists)
GET  /event-traces           ← change log (already exists)
GET  /causelist/{date}       ← full causelist for a date (NEW)
GET  /causelist/{date}/court/{court_no}  ← cases for one court (NEW)
WS   /ws/board               ← live board updates (optional, nice-to-have)
```

---

## 3. Causelist Data: What It Is

The Calcutta High Court publishes daily cause lists at:
```
https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{DD}{MM}{YYYY}.html
```

The HTML is a **table** (or sometimes plain-text formatted) listing every case scheduled for the day, per courtroom. Each row typically contains:

| Column | Example |
|---|---|
| Serial No (Sl. No.) | 1, 2, 3 … |
| Case Type | WPA, CAN, MAT, CS, etc. |
| Case Number | WPA/123/2024 |
| Year | 2024 |
| Petitioner | Ramesh Kumar |
| Respondent | State of WB & Ors |
| Petitioner's Advocate | Adv. Sharma |
| Respondent's Advocate | Adv. Gupta |
| Remarks / Matter | Urgent Motion |
| Court / Room No | 1 |

The existing `causelist_scraper.py` only extracts VC (Zoom) links. It ignores the full case table.

---

## 4. How to Extract Full Causelist Data

### 4a. Fetch Strategy

The HTML is public (no auth). Use **httpx** (already a dependency) instead of Playwright — it's a static HTML page:
```python
import httpx
resp = httpx.get(url, timeout=30)
html = resp.text
```
Only fall back to Playwright if the site requires JS rendering (it doesn't currently).

### 4b. Parsing Strategy

Use **BeautifulSoup4** (`beautifulsoup4` + `lxml` parser). The causelist HTML has `<table>` elements — one per courtroom, or one big table with court headers as row separators.

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, "lxml")
tables = soup.find_all("table")
```

The exact structure varies by year. Robust approach:
1. Find all `<table>` tags
2. For each table, detect if first row contains a court heading (e.g., "COURT NO. 1") or case columns
3. Parse headers from first `<tr>` → map to canonical column names
4. Parse each subsequent `<tr>` → one case dict

Header normalization (headers change year to year):
```python
HEADER_MAP = {
    "sl": "serial_no",
    "sl.": "serial_no",
    "sl. no.": "serial_no",
    "case no.": "case_number",
    "case number": "case_number",
    "petitioner": "petitioner",
    "applicant": "petitioner",   # some years use this
    "opposite party": "respondent",
    "respondent": "respondent",
    ...
}
```

### 4c. DB Schema for Causelist

```sql
CREATE TABLE causelist_case (
    id              BIGSERIAL PRIMARY KEY,
    list_date       DATE NOT NULL,          -- which day's causelist
    court_no        TEXT NOT NULL,          -- "1", "2", "VC-1" etc.
    serial_no       INTEGER,               -- position in that court's list
    case_type       TEXT,                  -- WPA, CAN, MAT, CS…
    case_number     TEXT,                  -- raw "123/2024"
    case_year       INTEGER,
    case_ref        TEXT,                  -- computed: "WPA/123/2024"
    petitioner      TEXT,
    respondent      TEXT,
    petitioner_adv  TEXT,
    respondent_adv  TEXT,
    remarks         TEXT,
    raw_json        JSONB,                 -- entire row, for future columns
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX causelist_case_unique
    ON causelist_case(list_date, court_no, serial_no);

CREATE INDEX causelist_case_date_court
    ON causelist_case(list_date, court_no);

CREATE INDEX causelist_case_ref
    ON causelist_case(case_ref);
```

`raw_json` stores the full parsed row so schema changes don't require re-scraping old data.

### 4d. Incremental Scraping

Run once per day, every  evening (courts publish by ~9 pM):
```
chd-scrape-causelist 2026-04-27
```

On conflict (re-run same date) → `ON CONFLICT (list_date, court_no, serial_no) DO UPDATE SET raw_json=excluded.raw_json, scraped_at=NOW()` — idempotent.

### 4e. Linking to Monitor Data

`causelist_case.serial_no` + `causelist_case.court_no` = `subscriptions.target_serial` + `subscriptions.room_no`.

This link lets notifications say "Your case **WPA/123/2024 (Ramesh Kumar v. State of WB)** is currently **serial 3** in Court 5" instead of just "serial 3 in room 5".

---

## 5. Which DB to Use

**Use PostgreSQL.** Specifically:

| Option | Verdict |
|---|---|
| **SQLite** (current) | Fine for single-machine dev. Can't be accessed from a remote frontend or multiple processes on different machines. No `LISTEN/NOTIFY`. |
| **PostgreSQL 16 self-hosted** | Best for full control. Run in Docker locally, deploy to Railway/Render free tier. |
| **Supabase (managed Postgres)** | Recommended for this project. Free tier: 500 MB, built-in REST API (`/rest/v1/`), built-in Realtime (WebSocket) for live board updates, PostgREST means you can skip writing some API endpoints entirely. |
| **PlanetScale / Neon** | Good Postgres alternatives; Neon has free serverless Postgres with branching. |
| **MongoDB** | Overkill, no benefit here — data is relational (cases, courts, subscriptions). |

**Recommendation: Supabase for production, local Postgres (Docker) for dev.**

```yaml
# docker-compose.yml (dev)
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: eventtrace
      POSTGRES_USER: eventtrace
      POSTGRES_PASSWORD: dev
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
```

---

## 6. Implementation Order

1. **Add Postgres support** — swap `DB` class, keep SQLite path behind `DATABASE_URL` env var
2. **Run pgloader** to migrate existing data
3. **Extend causelist_scraper.py** — add `scrape_full_causelist(date)` → BeautifulSoup table parse → `causelist_case` table
4. **Add API endpoints** — `GET /causelist/{date}` and `GET /causelist/{date}/court/{court_no}`
5. **Bootstrap frontend** — `npm create vite@latest frontend -- --template react-ts`
6. **Wire TanStack Query** to existing `/current-state` and new `/causelist` endpoints
7. **Add WebSocket** endpoint in FastAPI for live board pushes (optional but satisfying)

---

## 7. Dependencies to Add

```toml
# pyproject.toml additions
"psycopg2-binary>=2.9",      # or "asyncpg>=0.29" for async
"beautifulsoup4>=4.12",
"lxml>=5.0",
"alembic>=1.13",             # migrations (optional but recommended)
```

```json
// frontend package.json (key deps)
"@tanstack/react-query": "^5",
"@tanstack/react-table": "^8",
"react-router-dom": "^6",
"tailwindcss": "^4"
```

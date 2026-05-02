# EventTrace — Deployment & Architecture

## What We Built

**EventTrace** is a live court-hearing tracker for the High Court at Calcutta.
It scrapes the display board, detects changes, stores a full change log, and
serves the data through a REST API consumed by a React frontend.

The system is split into two repos deployed on two platforms:

| Repo | Platform | Role |
|------|----------|------|
| `EventTrace` | Railway | Python backend (FastAPI + scraper) |
| `EventTrace-Web` | Vercel | React frontend (Vite + TanStack Query) |

---

## Backend (EventTrace → Railway)

### Stack
- **FastAPI** — REST API, read-only for public routes
- **Playwright** — headless Chromium to scrape the court display board
- **SQLite / PostgreSQL** — dual backend; app picks based on `DATABASE_URL` env var
- **psycopg2** — PostgreSQL driver with connection pool (ThreadedConnectionPool)
- **uvicorn** — ASGI server

### Key files
| File | Purpose |
|------|---------|
| `src/eventtrace/api.py` | FastAPI app factory, all routes, CORS middleware |
| `src/eventtrace/db.py` | `DB` (SQLite) and `PostgresDB` classes, same public interface |
| `src/eventtrace/run_monitor.py` | Poll loop — scrapes and writes changes to DB |
| `src/eventtrace/causelist_parser.py` | Parses cause list HTML, stores case data |
| `src/eventtrace/config.py` | Settings loaded from env vars |
| `Dockerfile` | Multi-stage build: python:3.12-slim + Playwright Chromium |
| `railway.toml` | Build/deploy config for Railway |

### Database selection
```python
# get_db() in db.py
if DATABASE_URL:
    return PostgresDB(DATABASE_URL)   # Postgres on Railway
else:
    return DB("data/eventtrace.sqlite3")  # SQLite (local dev / ephemeral)
```

### CORS
All origins allowed (`*`) with `allow_credentials=False` — public read-only API,
no cookies or auth tokens flow through CORS.

### Docker build
```dockerfile
FROM python:3.12-slim
RUN apt-get install -y libpq-dev gcc curl
WORKDIR /app
RUN mkdir -p /app/data /app/.state   # SQLite dir + session cookie dir
COPY pyproject.toml . && COPY src/ src/
RUN pip install -e . && playwright install chromium --with-deps
ENV CHD_API_HOST=0.0.0.0
CMD ["chd-api"]
```

Railway injects `PORT` at runtime; app reads it:
```python
port = int(os.getenv("PORT") or os.getenv("CHD_API_PORT", "8009"))
```

### Postgres startup retry
`PostgresDB._get_pool()` retries the connection 10 times with 3s delay to handle
Railway's service startup race (app container sometimes starts before Postgres is ready).

---

## Frontend (EventTrace-Web → Vercel)

### Stack
- **React 18** + **TypeScript**
- **Vite 5** (build tool — compatible with Node 18)
- **Tailwind CSS v3** (PostCSS-based — no native binaries required)
- **TanStack Query v5** — data fetching, 15s auto-refresh on live board

### Key files
| File | Purpose |
|------|---------|
| `src/api/client.ts` | All API calls; `BASE` URL from `VITE_API_URL` env var |
| `src/pages/DisplayBoard.tsx` | Live court board, 15s refetch interval |
| `src/pages/Causelist.tsx` | Browse cause lists by date + court |
| `src/pages/CauselistSearch.tsx` | Search by advocate / party / case ref |
| `vercel.json` | SPA rewrite: all routes → `index.html` |

### API base URL
```typescript
const BASE = (import.meta.env.VITE_API_URL ?? 'https://eventtrace-production.up.railway.app')
  .replace(/\/$/, '');
```
Falls back to the Railway URL if `VITE_API_URL` is not set at build time.

### Tailwind v4 → v3 downgrade (why)
Tailwind v4 uses `@tailwindcss/oxide` (Rust native binary downloaded via postinstall
script). Environments that block postinstall scripts (sandboxed CI, `--ignore-scripts`)
never get the binary and crash. Tailwind v3 is pure JS/PostCSS — no native deps.

---

## Deployment Steps (reproduced)

### Railway (backend)
1. Push `EventTrace` to GitHub
2. Railway → New Project → Deploy from GitHub repo
3. Railway auto-detects `railway.toml`, builds Dockerfile
4. Add PostgreSQL service → Railway sets `DATABASE_URL` automatically
5. Set env vars: `TELEGRAM_TOKEN`, `TWILIO_*`, `CHD_ALERT_API_KEY`
6. Railway injects `PORT`; app binds to it

### Vercel (frontend)
1. Push `EventTrace-Web` to GitHub
2. Vercel → Import repository
3. Vercel auto-detects Vite
4. Set env var: `VITE_API_URL=https://eventtrace-production.up.railway.app`
5. Deploy — Vercel rebuilds on every push to `main`

---

## Bugs Fixed During This Work

| Bug | Cause | Fix |
|-----|-------|-----|
| `railway.toml` parse error | Flat keys `restartPolicyType` invalid in Railway v2 | Changed to `restartPolicy = { type = "on-failure", maxRetries = 3 }` |
| Healthcheck never responds | App bound to hardcoded port, Railway assigned different `PORT` | Read `os.getenv("PORT")` first |
| `sqlite3.OperationalError` on startup | `/app/data` dir missing in container | Added `RUN mkdir -p /app/data /app/.state` to Dockerfile |
| Postgres connection crash | `DATABASE_URL` pointed to localhost (no Postgres service) | Added 10x retry with 3s backoff in `_get_pool()` |
| CORS blocked by browser | `allow_credentials=True` + `allow_origins=["*"]` is invalid per CORS spec | Set `allow_credentials=False` with wildcard origin |
| Frontend hitting localhost in production | `VITE_API_URL` not set on Vercel; Vite bakes env vars at build time | Hardcoded Railway URL as fallback default in `client.ts` |
| Causelist scrape crash | `court_no=None` on preamble rows, f-string format failed before `--store` | `str(b['court_no'] or '?')` |
| `/vc-links/dates` 500 | `list_vc_dates()` missing from `PostgresDB` | Added method to both DB backends |

---

## Security Issues (Current)

### Active risks

| Issue | Severity | Detail |
|-------|----------|--------|
| `/admin` route unprotected | Medium | Serves admin HTML with no auth check — anyone can access it |
| `/export/*.csv` unprotected | Low | Full DB dumps accessible without auth |
| No rate limiting | Low | API has no request throttling; scraping/abuse possible |
| SQLite data is ephemeral | Info | Railway filesystem resets on redeploy — all SQLite data lost |
| CORS is fully open (`*`) | Info | Any website can call the API — acceptable for public data, but worth noting |

### Already safe
- Admin alert endpoint (`POST /alert`) protected by `CHD_ALERT_API_KEY` header check
- Twilio webhook verified by HMAC signature
- No secrets in source code — all via env vars
- HTTPS enforced by Railway and Vercel (TLS termination at edge)

### Recommended fixes
1. Add HTTP Basic Auth or a Bearer token check to `/admin` and `/export/*`
2. Add `slowapi` or Railway-level rate limiting
3. Add PostgreSQL service on Railway so data survives redeployments

# Security Hardening Plan

## Issue 1 — `/admin` route unprotected (Medium)

### Problem
`GET /admin` serves `admin.html` with no auth check whatsoever:
```python
@app.get("/admin", response_class=HTMLResponse)
def ui_admin():
    return HTMLResponse((_UI_DIR / "admin.html").read_text())
```
Anyone who knows the URL can access the admin panel.

### Fix — HTTP Basic Auth middleware

**Step 1.** Add `python-jose` or use stdlib only — no extra dep needed. Add to `api.py`:

```python
import secrets
from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_security = HTTPBasic()

def _require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "")
    if not admin_pass:
        raise HTTPException(status_code=503, detail="Admin not configured")
    ok_user = secrets.compare_digest(credentials.username.encode(), admin_user.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), admin_pass.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
```

**Step 2.** Add dependency to the route:
```python
@app.get("/admin", response_class=HTMLResponse)
def ui_admin(_: None = Depends(_require_admin)):
    return HTMLResponse((_UI_DIR / "admin.html").read_text())
```

**Step 3.** Set Railway env vars:
```
ADMIN_USER=your_username
ADMIN_PASSWORD=a_long_random_string
```

Generate a strong password:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Why `secrets.compare_digest`?** Prevents timing attacks — constant-time comparison so
an attacker cannot determine correctness by measuring response time.

---

## Issue 2 — `/export/*.csv` unprotected (Low)

### Problem
Both export endpoints return full database dumps with no auth:
- `GET /export/current-state.csv` — all current court states
- `GET /export/event-traces.csv` — full change log (up to 100k rows)

### Fix — reuse the same `_require_admin` dependency

```python
@app.get("/export/current-state.csv")
def export_current_state_csv(_: None = Depends(_require_admin)):
    ...

@app.get("/export/event-traces.csv")
def export_event_traces_csv(
    limit: int = Query(2000, ge=1, le=100000),
    court_id: str | None = None,
    _: None = Depends(_require_admin),
):
    ...
```

No new env vars needed — same `ADMIN_USER` / `ADMIN_PASSWORD`.

---

## Issue 3 — No rate limiting (Low)

### Problem
Every public API endpoint (`/current-state`, `/causelist/*`, `/event-traces`, etc.)
can be called unlimited times. A bot could hammer the server or scrape all data
in seconds.

### Fix — `slowapi` (thin wrapper around `limits` library)

**Step 1.** Add dependency to `pyproject.toml`:
```toml
[project]
dependencies = [
    ...
    "slowapi>=0.1.9",
]
```

**Step 2.** Wire into `api.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# Inside create_app(), after app = FastAPI(...):
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

**Step 3.** Decorate endpoints (or rely on default limit):
```python
@app.get("/current-state")
@limiter.limit("30/minute")   # tighter for heavy endpoints
def current_state(request: Request):
    ...
```

**Limits to set:**

| Endpoint | Suggested limit |
|----------|----------------|
| `/current-state` | 30/minute |
| `/event-traces` | 20/minute |
| `/causelist/search` | 20/minute |
| `/causelist/{date}` | 60/minute |
| `/export/*.csv` | 5/minute (already admin-only) |
| `/health` | unlimited |

### Alternative — Railway-level limiting
Railway Pro supports request rate limiting at the edge (no code change needed).
Check: Railway dashboard → service → Networking → Rate Limiting.

---

## Issue 4 — SQLite data is ephemeral on Railway (Info)

### Problem
Railway containers use an ephemeral filesystem. Every redeploy wipes `/app/data/`,
destroying all SQLite data: court states, event traces, cause list cases, alerts.

### Fix — Add PostgreSQL service on Railway

**Step 1.** Railway dashboard → project → **New Service** → **Database** → **PostgreSQL**

**Step 2.** Railway auto-injects `DATABASE_URL` into all services in the same project.
The app already switches backends automatically:
```python
# db.py — get_db()
if DATABASE_URL:
    return PostgresDB(DATABASE_URL)   # persistent
else:
    return DB("data/eventtrace.sqlite3")  # ephemeral
```

**Step 3.** Run schema migration once after Postgres is up:
```bash
railway run python -c "
from eventtrace.config import Settings
from eventtrace.db import get_db
get_db(Settings()).ensure_schema()
print('Schema ready')
"
```

**Cost:** Railway's hobby Postgres is free up to 1 GB. Court data is small — months of
operation will stay well under that.

**Data persistence after Postgres:** redeployments no longer wipe data. Only
`railway service delete` or `DROP TABLE` destroys it.

---

## Implementation Order

| Priority | Issue | Effort |
|----------|-------|--------|
| 1 | Add Postgres (data safety) | 10 min — UI only |
| 2 | Protect `/admin` + `/export/*` with HTTP Basic Auth | 30 min — code + deploy |
| 3 | Add `slowapi` rate limiting | 45 min — code + tune limits |

Start with Postgres — it protects all existing data before any code changes ship.

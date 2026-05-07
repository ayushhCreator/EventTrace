# EventTrace — Product Spec & Architecture

> Date: 2026-05-01  
> Scope: DB strategy, user model, search, wireframe, deployment, CI/CD, WhatsApp BSP, maintainability

---

## 1. Production Database Strategy

### Current state
Railway Postgres (Docker-managed). Fine for development. Not production-grade:
- No point-in-time recovery
- Manual backup required
- Railway costs scale badly at volume

### Recommendation: Supabase

| Feature | Supabase | Railway Postgres | Neon |
|---|---|---|---|
| Managed backups | Daily (free), PITR (pro) | Manual | PITR on pro |
| Built-in Auth | Yes | No | No |
| Row-Level Security | Yes | No | No |
| Real-time | Yes (WebSocket) | No | No |
| Free tier | 500MB DB, 50k MAU | No | 0.5 CU |
| Edge Functions | Yes | No | No |

Supabase wins because auth + RLS handles the entire subscription/permission model natively. Real-time handles live court updates without polling.

### Migration plan (one-time)
```bash
pg_dump $RAILWAY_DATABASE_URL > backup.sql
psql $SUPABASE_DATABASE_URL < backup.sql
# Update DATABASE_URL in Railway → point to Supabase
# Scraper/API keep working — same psycopg2 driver
```

### Backup strategy
- **Supabase free**: daily automated backup, 7-day retention
- **Supabase pro**: PITR up to 7 days
- **Extra safety**: weekly `pg_dump` cron via Railway scheduler → Google Drive or S3

---

## 2. User Hierarchy & Subscription Model

### Role hierarchy (low → high)

```
Client
  └─ track own case numbers, get hearing alerts

Clerk
  └─ manage cases for 1–N advocates, bulk tracking

Junior Counsel
  └─ own cases + assigned client cases

Counsel / Senior Counsel
  └─ full causelist view, firm-wide cases, judge-based search

Advocate on Record (AOR)
  └─ registered with court, manage client list, exports

Solicitor
  └─ firm-level access, all AORs under firm

Admin
  └─ full system access, user management
```

### Subscription tiers

| Tier | Who | Features |
|---|---|---|
| Free | Anyone | Search by case/advocate/party. View causelist. No account. |
| Basic | Client, Clerk | Track 5 cases. Email/WhatsApp alerts. |
| Pro | Junior/Senior Counsel | Unlimited tracking. Dashboard. PDF export. |
| Firm | AOR, Solicitor | Multi-user workspace. Shared dashboard. Bulk export. |

Pricing decided later. Launch free for all, gate premium features after user base grows.

### Supabase RLS enforcement

```sql
-- User sees only own tracked cases
CREATE POLICY "own cases"
ON tracked_cases USING (user_id = auth.uid());

-- Firm members see all firm cases
CREATE POLICY "firm cases"
ON tracked_cases USING (
  firm_id IN (SELECT firm_id FROM firm_members WHERE user_id = auth.uid())
);
```

Data isolation enforced at DB level — no app-layer bugs can leak data.

---

## 3. Search Architecture

### Search fields

| Field | Type | Notes |
|---|---|---|
| Case Number | Exact match | CNR or case_no — primary identifier |
| Party Name | Full-text | Petitioner / Respondent |
| Advocate Name | Full-text | Senior counsel, AOR, junior |
| Judge Name | Filter | Dropdown preferred |
| Court Number | Filter | Numeric dropdown |
| Date | Range filter | Hearing date from causelist |

### Postgres full-text index

```sql
ALTER TABLE causelist ADD COLUMN search_vector tsvector;

CREATE INDEX causelist_fts ON causelist USING GIN(search_vector);

CREATE TRIGGER causelist_search_update
BEFORE INSERT OR UPDATE ON causelist
FOR EACH ROW EXECUTE FUNCTION tsvector_update_trigger(
  search_vector, 'pg_catalog.english',
  case_number, petitioner, respondent, advocate, judge
);
```

### API endpoints

```
GET /search?q=sharma&field=advocate&date=2026-05-01&court=3
GET /search?q=WP(C)/1234/2024&field=case_number
GET /search?q=singh+v+haryana&field=party
```

---

## 4. Frontend Wireframe

### Public pages (no login)

```
Landing Page
├── Hero: "Track your case in real-time"
├── Search bar (full-width)
│   └── Tabs: [Case No] [Advocate] [Party Name] [Judge]
├── Results table: Case No | Parties | Advocate | Court | Next Date
└── CTA: "Get hearing alerts → Sign up free"

Causelist Page
├── Date picker (default: today)
├── Filter bar: Court No ▼  Judge ▼
├── Table: Serial | Case No | Parties | Advocate | Court | Time
└── [Track] button per row (requires login)
```

### Authenticated dashboard

```
Dashboard
├── My Cases (cards)
│   ├── Case no + parties
│   ├── Next date (highlighted if today)
│   ├── Status badge ("Order passed", "Adjourned")
│   └── [View history] [Remove]
│
├── Today's Causelist (filtered to my cases only)
│   └── Court | Time | Case | Status
│
├── Timeline Chart
│   ├── X: dates, Y: event type
│   └── Click → event trace detail modal
│
└── Notifications
    ├── "WP(C)/1234 listed today — Court 3"
    └── Settings: Email / WhatsApp / In-app
```

### Chart ↔ Table linkage

```
Causelist Table row (click)
    ↓
Case Detail panel (slide-in)
    ├── event_trace table → Timeline chart (recharts/visx)
    ├── current_state table → Current values grid
    ├── field_state table → Per-field history
    └── [Track] [Share] [Export PDF]
```

### Firm workspace (Firm tier)

```
Firm Dashboard
├── All cases across all firm members
├── Assign case → colleague
├── Shared notes per case
├── Export: CSV / PDF
└── Members: invite by email, set role
```

---

## 5. Full System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXTERNAL                                  │
│  Court website (principal.php / display_api.json / causelist)   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ scrape (Playwright)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RAILWAY (backend)                             │
│                                                                  │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │ run_monitor    │  │ causelist_sched   │  │ FastAPI (api.py)│ │
│  │ (scraper loop) │  │ (daily fetch)     │  │ port = $PORT    │ │
│  └───────┬────────┘  └────────┬─────────┘  └────────┬────────┘ │
│          │                    │                       │          │
│          └──────────┬─────────┘              reads only         │
│                     │ write                         │            │
└─────────────────────┼───────────────────────────────┼───────────┘
                      │                               │
                      ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SUPABASE                                      │
│                                                                  │
│  Tables:                                                         │
│  ├── current_state      (latest court row per court_id)          │
│  ├── field_state        (current value + start_time per field)   │
│  ├── event_trace        (append-only change log)                 │
│  ├── causelist          (daily case listings, FTS indexed)       │
│  ├── users              (Supabase Auth managed)                  │
│  ├── tracked_cases      (user → case mapping, RLS enforced)      │
│  ├── firms              (firm accounts)                          │
│  └── firm_members       (user → firm mapping)                    │
│                                                                  │
│  Features used:                                                  │
│  ├── Auth (email + Google OAuth)                                 │
│  ├── Row-Level Security (subscription enforcement)               │
│  ├── Realtime (WebSocket push to frontend)                       │
│  └── Daily automated backups                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┴──────────────┐
              │ REST (FastAPI)            │ WebSocket (Supabase Realtime)
              ▼                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VERCEL (frontend)                             │
│                                                                  │
│  React + Vite + TypeScript + Tailwind                           │
│  TanStack Query (REST calls to FastAPI)                         │
│  Supabase JS client (auth + realtime)                           │
│                                                                  │
│  Pages:                                                          │
│  ├── / (landing + search)                                        │
│  ├── /causelist (browse by date)                                 │
│  ├── /dashboard (auth required)                                  │
│  ├── /case/:id (detail + timeline chart)                         │
│  └── /firm (Firm tier only)                                      │
└─────────────────────────────────────────────────────────────────┘
                           │
              notification triggers
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                 NOTIFICATION LAYER                               │
│                                                                  │
│  Supabase Edge Function (daily trigger)                          │
│  ├── Resend (email)       — free: 3k emails/mo                   │
│  └── WhatsApp BSP         — see Section 8                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Deployment Architecture

### Where each piece lives

| Service | Platform | Why |
|---|---|---|
| FastAPI backend | Railway | Already deployed, Docker builds, env vars easy |
| Scraper (monitor) | Railway | Separate service, same repo |
| Causelist scheduler | Railway | Separate service, same repo |
| Frontend | Vercel | Auto CDN, free for public sites, Git push → deploy |
| Database | Supabase | Auth + RLS + backups + realtime |
| Notifications | Supabase Edge Functions | No extra server |
| Custom domain | Vercel (frontend) + Railway (API) | Both support custom domains |

### Custom domain setup

```
yourdomain.in         → Vercel (frontend)
api.yourdomain.in     → Railway (FastAPI)
```

Railway custom domain: Dashboard → Service → Settings → Networking → Custom Domain.  
Vercel custom domain: Settings → Domains → Add.

Add CNAME records in your DNS registrar (GoDaddy/Cloudflare/Namecheap).

### Environment variables (full list)

**Railway (backend):**
```
DATABASE_URL=postgresql://...supabase...   # Supabase connection string
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=...                   # server-side only, full access
TELEGRAM_TOKEN=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
ADMIN_USER=...
ADMIN_PASSWORD=...
CHD_ALERT_API_KEY=...
```

**Vercel (frontend):**
```
VITE_API_URL=https://api.yourdomain.in
VITE_SUPABASE_URL=https://xxx.supabase.co
VITE_SUPABASE_ANON_KEY=...                 # public, safe to expose
```

---

## 7. CI/CD Pipeline

### Strategy: GitHub Actions + automatic platform deployments

Both Railway and Vercel deploy automatically on push to `main`. GitHub Actions adds:
- Lint + type check before merge (blocks broken code)
- Test run on PRs
- Separate staging environment on PRs (optional)

### File: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: .   # EventTrace repo root
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check src/
      - run: ruff format --check src/
      - run: pytest tests/ -x -q   # once tests exist

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ../EventTrace-Web   # adjust if monorepo
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npm run type-check   # tsc --noEmit
      - run: npm run lint         # eslint
      - run: npm run build        # fails fast if Vite build breaks
```

### Branching model

```
main          → production (Railway + Vercel auto-deploy)
feature/*     → PRs → CI runs → merge to main
hotfix/*      → PRs → merge directly to main with fast-track review
```

No staging environment needed at this scale. Add it when you have 100+ users.

### Deploy flow

```
git push origin main
       │
       ├─→ GitHub Actions: lint + type-check + tests
       │        (if fails → deploy blocked)
       │
       ├─→ Railway: rebuilds Docker image, deploys backend
       │        healthcheck at /health before traffic switches
       │
       └─→ Vercel: rebuilds React app, deploys to CDN
                rollback to previous deployment in 1 click
```

---

## 8. WhatsApp Notifications (BSP Setup)

### Options compared

| Provider | Setup | Cost | Notes |
|---|---|---|---|
| **Twilio** | Medium | $0.005/msg + monthly WhatsApp fee | Most reliable, global |
| **WATI** | Easy | ₹2,499/mo (800 msgs) | India-focused, good UX, template approvals easier |
| **Interakt** | Easy | ₹999/mo | Indian BSP, Hindi support, good for small teams |
| **360dialog** | Hard | €49/mo | Direct Meta partner, cheapest at scale |

**Recommendation for MVP: WATI** — fastest setup in India, no per-message fee below quota, template approval in 24–48 hours.  
**Scale to Twilio** once volume exceeds WATI's plan.

### Step-by-step: WATI setup

**Step 1 — Get WhatsApp Business API access**
1. Go to wati.io → Start Free Trial
2. Connect your WhatsApp Business phone number
3. Submit business verification (GSTIN or company registration)
4. Meta approves in 1–3 business days

**Step 2 — Create message template**
Templates must be pre-approved by Meta before sending. Submit:
```
Template name: case_hearing_alert
Category: UTILITY
Language: English (en)

Body:
"Your case {{1}} is listed for hearing on {{2}} at {{3}} in Court No. {{4}}. 
— EventTrace"

Variables: case_number, date, time, court_no
```
Approval: 24–48 hours typically.

**Step 3 — Get WATI API credentials**
From WATI dashboard: API Endpoint URL + Access Token.

**Step 4 — Code integration**

```python
# src/eventtrace/notifications.py
import httpx

WATI_API_URL = os.getenv("WATI_API_URL")      # https://live-xxx.wati.io
WATI_ACCESS_TOKEN = os.getenv("WATI_TOKEN")

def send_whatsapp_alert(phone: str, case_number: str, date: str, time: str, court: str):
    """Phone must be in E.164 format: 919876543210 (no + prefix for WATI)"""
    url = f"{WATI_API_URL}/api/v1/sendTemplateMessage"
    payload = {
        "template_name": "case_hearing_alert",
        "broadcast_name": "hearing_alert",
        "receivers": [
            {
                "whatsappNumber": phone,
                "customParams": [
                    {"name": "1", "value": case_number},
                    {"name": "2", "value": date},
                    {"name": "3", "value": time},
                    {"name": "4", "value": court},
                ]
            }
        ]
    }
    headers = {"Authorization": f"Bearer {WATI_ACCESS_TOKEN}"}
    r = httpx.post(url, json=payload, headers=headers, timeout=10)
    r.raise_for_status()
```

**Step 5 — Railway env vars**
```
WATI_API_URL=https://live-xxx.wati.io
WATI_TOKEN=eyJhbGci...
```

**Step 6 — Trigger logic**

Daily cron (Supabase Edge Function or Railway scheduler):
1. Fetch tomorrow's causelist from DB
2. Join with `tracked_cases` table (which users track which cases)
3. For each match → send WhatsApp alert

```python
# Pseudo-code for notification worker
def send_daily_alerts():
    tomorrow = date.today() + timedelta(days=1)
    hearings = db.get_causelist(tomorrow)
    
    for hearing in hearings:
        users = db.get_users_tracking_case(hearing.case_number)
        for user in users:
            if user.whatsapp_enabled and user.phone:
                send_whatsapp_alert(
                    user.phone,
                    hearing.case_number,
                    tomorrow.strftime("%d %b %Y"),
                    hearing.time or "as per board",
                    hearing.court_no
                )
```

---

## 9. Maintainability Plan

### Code structure (current)

```
EventTrace/                   # backend repo
├── src/eventtrace/
│   ├── api.py                # FastAPI app, all routes
│   ├── db.py                 # DB abstraction (SQLite + Postgres)
│   ├── run_monitor.py        # scraper poll loop
│   ├── change_detector.py    # diff + event emission
│   ├── causelist_parser.py   # parse + store causelist
│   ├── backfill.py           # historical backfill
│   ├── notifications.py      # email + WhatsApp sending
│   └── config.py             # Settings from env vars
├── scripts/                  # Railway start scripts
├── docs/                     # all MD documentation
├── tests/                    # unit + integration tests (to add)
├── Dockerfile
├── railway.toml
└── pyproject.toml

EventTrace-Web/               # frontend repo
├── src/
│   ├── api/client.ts         # all API calls
│   ├── components/           # reusable UI components
│   ├── pages/                # page-level components
│   ├── hooks/                # custom React hooks
│   └── types/                # TypeScript types
├── vercel.json
└── package.json
```

### Rules to keep code maintainable as project grows

1. **Never hardcode column names** — headers detected dynamically each scrape (already done)
2. **DB abstraction stays** — `DB` and `PostgresDB` share interface; swap without app changes
3. **Config from env only** — no `if DEBUG:` blocks in production code paths
4. **One entry point per process** — `chd-api`, `chd-run-monitor`, `chd-schedule-causelist`, `chd-backfill`
5. **Tests before features** — add `pytest` tests for any new DB method or API endpoint
6. **Migrations with Alembic** — once Supabase is set up, use `alembic` for schema changes (not raw SQL)

### Adding Alembic (schema migrations)

```bash
pip install alembic
alembic init migrations
# Edit alembic.ini: sqlalchemy.url = %(DATABASE_URL)s
# Edit migrations/env.py: target_metadata = Base.metadata
alembic revision --autogenerate -m "add tracked_cases table"
alembic upgrade head
```

Add to `scripts/start-api.sh`:
```sh
alembic upgrade head   # runs migrations before API starts
exec chd-api
```

### Monitoring & observability

| What to watch | Tool | Where |
|---|---|---|
| API uptime | Railway built-in health checks | Railway dashboard |
| Error rates | Sentry (free tier: 5k errors/mo) | `pip install sentry-sdk` |
| Slow queries | Supabase Dashboard → Query Performance | Supabase UI |
| Scraper failures | Telegram bot alert (already wired) | Telegram |
| Frontend errors | Vercel Analytics (free) | Vercel dashboard |

Add Sentry:
```python
# api.py — top of file
import sentry_sdk
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.1)
```

---

## 10. Two-Week Launch Timeline

### Week 1 — Backend + Auth + Search (Days 1–7)

| Day | Task | Output |
|---|---|---|
| 1 | Create Supabase project + migrate DB | Supabase live |
| 1 | Update `DATABASE_URL` in Railway | API still works |
| 2 | Add `users`, `tracked_cases`, `firms`, `firm_members` tables + Alembic | Schema ready |
| 2 | Enable Supabase Auth (email + Google OAuth) | Auth working |
| 3 | Full-text search index on `causelist` | FTS ready |
| 3 | `/search` endpoint in FastAPI | Search API done |
| 4 | `/track-case` POST endpoint + RLS policies | Case tracking + isolation |
| 5 | Notification worker: daily causelist → WhatsApp/email alerts | Alerts working |
| 5 | WATI template submitted for Meta approval | Template pending |
| 6 | GitHub Actions CI workflow | Lint/type-check on every PR |
| 7 | Buffer + bug fixes | Week 1 stable |

### Week 2 — Frontend + Polish + Launch (Days 8–14)

| Day | Task | Output |
|---|---|---|
| 8 | Landing page + search bar | Public search live |
| 8 | Causelist page with date picker + filters | Causelist browsable |
| 9 | Auth flow (sign up, log in, Google OAuth) | Auth UI working |
| 9 | Dashboard: My Cases panel | Case tracking UI |
| 10 | Case detail panel + timeline chart (recharts) | History chart |
| 10 | Subscription gate (upgrade prompt for Pro features) | Paywall logic |
| 11 | Sentry integration (backend + frontend) | Error monitoring |
| 11 | Custom domain setup (Vercel + Railway) | Domain live |
| 12 | WhatsApp alert opt-in in user settings | Alerts wired |
| 13 | End-to-end test: free → basic → pro flow | Full flow tested |
| 14 | Production smoke test + announce | LIVE |

### What Firm tier needs (post-launch, ~Month 2)
- Firm invite system (email → join firm)
- Case assignment UI
- Shared notes (just a `notes` table with `firm_id`)
- Bulk export (already have CSV export, just add firm filter)

---

## 11. Open Questions (resolve before Day 1)

| Question | Status |
|---|---|
| Custom domain name? | Decided — to be purchased |
| WhatsApp phone number for BSP? | Need dedicated number for WATI |
| Razorpay KYC? | Later — launch free first |
| Prices? | Launch free, decide later |
| Firm tier at launch? | No — post-launch Month 2 |
| Sentry DSN? | Create free account at sentry.io |

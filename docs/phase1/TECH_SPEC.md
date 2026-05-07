# EventTrace — Phase 1 Technical Specification

> **For:** Engineering Team  
> **Phase:** 1 — Core Product  
> **Version:** 1.0 | May 2026  
> **Status:** Living document — update as features complete

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Infrastructure — Where Things Live](#2-infrastructure--where-things-live)
3. [Phase 1 — Features Built](#3-phase-1--features-built)
   - 3.1 [Real-time Court Monitor](#31-real-time-court-monitor)
   - 3.2 [Causelist Scraper and Parser](#32-causelist-scraper-and-parser)
   - 3.3 [Search System](#33-search-system)
   - 3.4 [Authentication System](#34-authentication-system)
   - 3.5 [Case Tracking API](#35-case-tracking-api)
   - 3.6 [Frontend Pages](#36-frontend-pages)
4. [Phase 1 — Features Pending](#4-phase-1--features-pending)
   - 4.1 [Alert Delivery System](#41-alert-delivery-system)
   - 4.2 [Case History Timeline](#42-case-history-timeline)
   - 4.3 [My Cases Data Enrichment](#43-my-cases-data-enrichment)
   - 4.4 [URL Routing](#44-url-routing)
   - 4.5 [Production Env Gaps](#45-production-env-gaps)
5. [Database Schema — Current State](#5-database-schema--current-state)
6. [API Reference — Phase 1 Endpoints](#6-api-reference--phase-1-endpoints)
7. [Data Flow Diagrams](#7-data-flow-diagrams)
8. [Phase 2 Roadmap — Technical Preview](#8-phase-2-roadmap--technical-preview)
9. [Technical Questions and Open Issues](#9-technical-questions-and-open-issues)

---

## 1. System Overview

EventTrace is a Python/FastAPI backend + React/TypeScript frontend platform. Four independent processes share a single PostgreSQL database:

```
┌────────────────────────────────────────────────────────────────┐
│                     PROCESSES (Railway)                         │
│                                                                  │
│  run_monitor          → scrape display_api.json every 15s       │
│  schedule_causelist   → download + parse daily causelist HTML   │
│  api                  → FastAPI server (read + auth + write)    │
│  [init_session]       → one-time manual CAPTCHA bypass          │
└────────────────────────────────────────────────────────────────┘
                    │ all read/write
                    ▼
┌────────────────────────────────────────────────────────────────┐
│                   PostgreSQL (Supabase)                          │
│   event_trace, field_state, current_state                       │
│   causelist_bench, causelist_case                               │
│   users, tracked_cases, subscriptions, notification_log         │
└────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│                    Frontend (Vercel)                             │
│   React 18 + TypeScript + Tailwind + Vite + TanStack Query      │
│   EventTrace-Web repo at /home/ayush-raj/The_Base/EventTrace-Web│
└────────────────────────────────────────────────────────────────┘
```

**DB backend selection** (`db.py`):
- `DATABASE_URL` set → `PostgresDB` (psycopg2 connection pool)
- `DATABASE_URL` empty → `DB` (SQLite WAL, local dev)
- `get_db(settings)` factory used by all processes

---

## 2. Infrastructure — Where Things Live

| Component | Technology | Host | URL |
|---|---|---|---|
| Frontend | React + Vite + TypeScript + Tailwind | Vercel | auto-deploy on push |
| API | Python FastAPI | Railway | `http://127.0.0.1:8009` locally |
| Live Monitor | Python + Playwright | Railway | background process |
| Causelist Scheduler | Python + Playwright | Railway | background process |
| Database | PostgreSQL 15 | Supabase (ap-south-1) | DATABASE_URL in env |
| Session state | JSON file | Railway volume | `.state/storage_state.json` |

**Local dev commands:**
```bash
source .venv/bin/activate
chd-api                    # FastAPI on :8009
chd-run-monitor            # live scraper loop
chd-schedule-causelist     # causelist daily job
```

---

## 3. Phase 1 — Features Built

### 3.1 Real-time Court Monitor

**Files:** `src/eventtrace/run_monitor.py`, `scraper.py`, `change_detector.py`

**How it works end-to-end:**

```
1. run_monitor.py starts a poll loop (interval ~15s)
2. scraper.scrape_table_once_sync() called:
   - Playwright navigates to principal.php
   - In-page JS is executed to fetch display_api.json
   - This endpoint is public (no CAPTCHA) — CAPTCHA only on the HTML page
   - Returns list[dict] — one dict per court row
3. _build_court_id() creates a stable key per court
   - Default: joins CHD_KEY_FIELDS columns (default: court_no)
   - CHD_KEY_FIELDS can be comma-separated for composite keys
4. change_detector.apply_snapshot() called with the new snapshot:
   - Compares each court's fields against field_state table
   - For each changed field → writes an EventTrace record (event_trace table)
   - Also tracks court presence via synthetic __present__ field
   - field_state.start_time records when the *current* value was first seen
   - duration_seconds in event_trace = end_time - start_time at write time
5. current_state table updated with latest full row per court
```

**Key design decisions:**
- Headers detected dynamically each scrape — no hardcoded column names
- Serial ranges compressed: `[1,2,3,15,16]` → `"1-3,15-16"`
- VC links scraped separately across 4 time windows (0h, 6h, 8h, 20h IST)
- Session cookies persisted to `.state/storage_state.json` to survive across restarts
- `__present__` synthetic field tracks courts going offline/returning

**Tables written:**
- `current_state` — latest full row per court (JSON blob)
- `field_state` — current value + start_time per (court, field)
- `event_trace` — append-only change log

---

### 3.2 Causelist Scraper and Parser

**Files:** `src/eventtrace/causelist_scraper.py`, `causelist_parser.py`, `schedule_causelist.py`

**How it works end-to-end:**

```
1. Schedule: runs retry windows 20:30 → 22:00 IST (4 attempts)
2. Playwright navigates to CHC website and fetches causelist HTML
3. 4 sources scraped independently:
   - appellate_static    (main appellate side daily list)
   - original_static     (original side daily list)
   - appellate_dynamic   (dynamic appellate)
   - original_dynamic    (dynamic original)
4. causelist_parser.py processes each HTML block:
   - Detects bench headers (judge names, court number)
   - Extracts section/subsection labels (GROUP-IX, PIL, TRIBUNAL etc.)
   - Parses each case row: serial_no, case_ref, petitioner, respondent, advocate, IA numbers
   - Handles DAILY / SPECIAL / MONTHLY list types
5. Data written to:
   - causelist_bench: one row per bench per date per side
   - causelist_case: one row per case per bench
6. Backfill: historical dates can be scraped with --backfill flag
```

**Key design decisions:**
- `bench_id` FK maps every case to its bench — enables fast court+date queries
- `section` + `subsection` on causelist_case capture in-bench category headers
- `jurisdiction` on causelist_bench stores full header text block
- `DAILY / SPECIAL / MONTHLY` list_type filters supported in API and frontend
- UPSERT on conflict (idempotent re-scrape)

**Tables written:**
- `causelist_bench` — court + date + side + list_type + judges
- `causelist_case` — case rows linked to bench_id

---

### 3.3 Search System

**Files:** `src/eventtrace/api.py` (`/causelist/search`), `src/eventtrace/causelist_search.py`

**How search works when a user types a query:**

```
User types "Sharma" in Advocate Name field
    │
    ▼ POST /causelist/search?advocate=Sharma
    │
    ▼ Search query built in Python:
    │   - case_ref search → ILIKE 'WP%' (prefix match)
    │   - advocate search → trigram index (pg_trgm) on causelist_case.advocate
    │   - party search    → trigram index on petitioner + respondent
    │   - judge search    → ILIKE on causelist_bench.judges_json::text
    │
    ▼ PostgreSQL executes:
    │   SELECT cc.*, cb.judges_json, cb.bench_label
    │   FROM causelist_case cc
    │   JOIN causelist_bench cb ON cb.id = cc.bench_id
    │   WHERE cc.advocate ILIKE '%Sharma%'
    │     AND (date_from filter if provided)
    │     AND (side filter if provided)
    │   ORDER BY cc.list_date DESC
    │   LIMIT 100
    │
    ▼ Results returned as JSON:
      [{case_ref, serial_no, list_date, court_no, petitioner, respondent, advocate, bench_label, judges}]
    │
    ▼ Frontend (CauselistSearch.tsx) renders results table
```

**Indexes in use:**
- `pg_trgm` trigram indexes on `petitioner`, `respondent`, `advocate` — enables fast fuzzy/partial match
- `idx_causelist_case_ref` — for exact case_ref lookups
- `idx_causelist_case_date` — for date-range filters

**Filters available:**
- `case_ref` — prefix or exact
- `advocate` — partial match
- `party` (searches petitioner OR respondent)
- `judge` — partial match on bench judges
- `date_from`, `date_to` — range filter
- `side` — APPELLATE / ORIGINAL
- `list_type` — DAILY / SPECIAL / MONTHLY

---

### 3.4 Authentication System

**Files:** `src/eventtrace/auth.py`, `src/eventtrace/models.py`

**Phone OTP flow:**

```
User enters phone number
    │
    ▼ POST /auth/send-otp  {phone: "+91XXXXXXXXXX"}
    │   - Rate limit: 60s cooldown per phone (checked in DB)
    │   - Generate 6-digit OTP
    │   - Store OTP hash + expiry in DB
    │   - PROD: send via MSG91 HTTP API
    │   - DEV: log OTP to stdout (shown in browser banner)
    │
    ▼ User receives OTP, enters it
    │
    ▼ POST /auth/verify-otp  {phone, otp}
    │   - Check max 5 attempts (invalidate on exceed)
    │   - Verify OTP hash
    │   - Lookup or create user in users table
    │   - Issue JWT (HS256, 30-day expiry)
    │   - Return {token, is_new_user}
    │
    ▼ Frontend stores JWT in localStorage as "et_token"
    │
    ▼ All authenticated requests: Authorization: Bearer <token>
```

**JWT payload:**
```json
{"sub": "<user_id>", "phone": "+91...", "exp": <unix_timestamp>}
```

**Profile update:**
```
PATCH /auth/me  {name, email}  → updates users table
GET  /auth/me                  → returns {id, phone, name, email, created_at}
```

**Known gap:** On 401 (expired JWT), the frontend currently silently breaks instead of showing "Session expired — please sign in."

---

### 3.5 Case Tracking API

**Files:** `src/eventtrace/my_cases.py`

**Endpoints and behavior:**

```
POST /my-cases
  Body: {case_ref: "WPA/101/2026"}
  Action: INSERT into tracked_cases (user_id, case_ref)
  Returns: tracked case record

GET /my-cases
  Returns: list of tracked cases for authenticated user
  Missing: last_seen_date, last_seen_court, next_hearing_date (not yet queried)

DELETE /my-cases/{case_ref}
  Removes tracking for this user+case_ref

POST /my-cases/{case_ref}/alert
  Body: {alert_serial: 10, look_ahead: 2}
  Sets: alert fires when live board serial >= (alert_serial - look_ahead)
  Stored in: tracked_cases.alert_serial + look_ahead columns

DELETE /my-cases/{case_ref}/alert
  Clears alert settings
```

**tracked_cases schema:**
```sql
CREATE TABLE tracked_cases (
  id           SERIAL PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id),
  case_ref     TEXT NOT NULL,
  alert_serial INT,
  look_ahead   INT DEFAULT 0,
  alert_active BOOLEAN DEFAULT TRUE,
  alerted_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, case_ref)
);
```

**What's NOT wired yet:**
- Monitor loop does not check `alert_serial` against live serial — alerts do not fire
- `last_seen_date`, `last_seen_court`, `next_hearing_date` not computed in GET /my-cases

---

### 3.6 Frontend Pages

**Repo:** `/home/ayush-raj/The_Base/EventTrace-Web`  
**Stack:** React 18 + TypeScript + Tailwind CSS + Vite + TanStack Query

| Page | File | Status | What it does |
|------|------|--------|---|
| Auth | `AuthPage.tsx` | ✓ Working | Phone + OTP flow; dev mode shows OTP in banner |
| Display Board | `DisplayBoard.tsx` | ✓ Working | Live court grid; event traces; VC links; absent courts |
| Causelist | `Causelist.tsx` | ✓ Working | Date picker → courts list → cases list; side/list_type filters |
| Search | `CauselistSearch.tsx` | ✓ Working | Full search with all filters |
| My Cases | `MyCases.tsx` | ✓ Built | Track/untrack cases; set serial alerts |
| Profile | `ProfilePage.tsx` | ✓ Built | Display/edit name, email; tier badge |

**API client:** `src/api/client.ts` — covers all backend endpoints  
**Auth:** JWT stored in `localStorage` as `et_token`, attached as Bearer in all API requests  
**Navigation:** Tab-based, no URL routing yet (pages are not bookmarkable)  
**State:** TanStack Query (React Query) for all server state; refetch intervals on DisplayBoard

---

## 4. Phase 1 — Features Pending

### 4.1 Alert Delivery System

**Phase 1 scope: Email only via Resend. WhatsApp moved to Phase 2** (requires DLT/TRAI regulatory approval — external dependency that would block launch).

**Part A — Evening causelist alert (Phase 1 — email):**
```python
# After causelist scrape completes for tomorrow's date:
def send_causelist_alerts(target_date: str, db):
    matches = db.query("""
        SELECT tc.user_id, u.email, tc.case_ref, cc.serial_no, cc.court_no
        FROM tracked_cases tc
        JOIN causelist_case cc ON cc.case_ref = tc.case_ref
        JOIN users u ON u.id = tc.user_id
        WHERE cc.list_date = $1
          AND u.email IS NOT NULL
    """, [target_date])
    for match in matches:
        send_email(
            to=match.email,
            subject=f"Case listed tomorrow — {match.case_ref}",
            body=f"Your case {match.case_ref} is listed tomorrow in Court {match.court_no}, Serial {match.serial_no}."
        )
        db.execute("INSERT INTO notification_log(user_id, case_ref, channel, message) VALUES($1,$2,'email',$3)",
                   [match.user_id, match.case_ref, f"Listed tomorrow Court {match.court_no}"])
```

**Part B — Serial-based alert check (Phase 1 — email, fires when threshold crossed):**
```python
# In run_monitor.py, after apply_snapshot():
def check_serial_alerts(court_id: str, current_serial: int, db):
    cases = db.query("""
        SELECT tc.user_id, u.email, tc.case_ref, tc.alert_serial, tc.look_ahead
        FROM tracked_cases tc
        JOIN users u ON u.id = tc.user_id
        WHERE tc.alert_active = TRUE
          AND tc.alert_serial IS NOT NULL
          AND tc.alerted_at::date < CURRENT_DATE
    """)
    for case in cases:
        threshold = case.alert_serial - case.look_ahead
        if current_serial >= threshold:
            send_email(case.email, f"Court {court_id} now at Serial {current_serial} — your case approaching")
            db.execute("UPDATE tracked_cases SET alerted_at=NOW() WHERE id=$1", [case.id])
```

**Phase 1 only dependency:** Resend API key — no regulatory approval needed.

**Phase 2 addition (WhatsApp):**
- Replace `send_email()` with `send_whatsapp()` via MSG91/WATI
- Requires DLT template approval from TRAI (start process during Phase 1 build)
- MSG91 WhatsApp: `MSG91_WHATSAPP_AUTH_KEY` + approved template ID
- WATI alternative: Meta Business Manager approval (24–48h)
- Same logic, different delivery channel — no DB changes needed

**Notification log table exists:** `notification_log (user_id, case_ref, channel, sent_at, message)`

---

### 4.2 Case History Timeline

**What needs to be built:**

**New tables:**
```sql
CREATE TABLE case_snapshots (
  id          SERIAL PRIMARY KEY,
  case_ref    TEXT NOT NULL,
  list_date   DATE NOT NULL,
  data_json   JSONB NOT NULL,
  hash        TEXT NOT NULL,      -- SHA256(data_json) for fast diff
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(case_ref, list_date)
);

CREATE TABLE case_timeline_events (
  id             SERIAL PRIMARY KEY,
  user_id        TEXT NOT NULL,
  case_ref       TEXT NOT NULL,
  event_type     TEXT NOT NULL,   -- TRACK_STARTED | NO_CHANGE | UPDATED | NOT_FOUND
  event_date     DATE NOT NULL,
  change_summary JSONB,           -- JSON diff, null for NO_CHANGE
  created_at     TIMESTAMPTZ DEFAULT NOW()
);
```

**Daily diff job (post-causelist-scrape):**
1. For each unique tracked `case_ref` across all users
2. Look up in today's `causelist_case`
3. Not found → write `NOT_FOUND` event
4. Found → compute SHA256 of case data
5. Hash matches last snapshot → write `NO_CHANGE` event
6. Hash differs → write JSON diff + `UPDATED` event + new snapshot

**New endpoint:**
```
GET /case/{case_ref}/timeline?limit=30
Returns: list of timeline events ordered by date DESC
Auth required
```

**Frontend:** Timeline component in `MyCases.tsx` — vertical timeline with event type icons

---

### 4.3 My Cases Data Enrichment

**Current gap in `GET /my-cases`:** missing three fields per case.

**Fix needed in `my_cases.py`:**
```python
# Add to the GET /my-cases query:

last_seen = db.query("""
    SELECT case_ref, MAX(list_date) as last_seen_date, 
           court_no as last_seen_court
    FROM causelist_case
    WHERE case_ref = ANY($1::text[])
    GROUP BY case_ref, court_no
    ORDER BY last_seen_date DESC
""", [case_refs])

next_hearing = db.query("""
    SELECT case_ref, MIN(list_date) as next_hearing_date
    FROM causelist_case
    WHERE case_ref = ANY($1::text[])
      AND list_date > CURRENT_DATE
    GROUP BY case_ref
""", [case_refs])
```

**Effort:** ~0.5 day

---

### 4.4 URL Routing

**Current:** All navigation is tab-based — no URLs. Pages cannot be bookmarked or linked.

**Fix:** Add React Router.

**Target routes:**
```
/               → Display Board
/causelist      → Causelist browser (?date= param)
/search         → Case search (?q= param)
/my-cases       → My Cases dashboard
/profile        → Profile page
/case/:case_ref → Case detail + timeline
```

**Effort:** ~0.5 day

---

### 4.5 Production Env Gaps

**CRITICAL — must fix before go-live:**

| Env Var | Status | Impact |
|---|---|---|
| `JWT_SECRET` | NOT SET — using default | All JWTs signed with default key. Anyone who knows the default can forge tokens. **Set before launch.** |
| `MSG91_AUTH_KEY` | Not set | OTP will not send in production — users cannot log in |
| `MSG91_TEMPLATE_ID` | Not set | OTP SMS format not registered |
| `DATABASE_URL` | Set | OK |
| `VITE_API_URL` | Set | OK |

---

## 5. Database Schema — Current State

### Core tables (monitor)

```sql
current_state (court_id, data_json, updated_at)
field_state   (court_id, field_name, current_value, start_time)
event_trace   (id, court_id, field_name, old_value, new_value, start_time, end_time, duration_seconds)
```

### Causelist tables

```sql
causelist_bench (id, list_date, court_no, bench_label, judges_json, side, list_type, jurisdiction, not_sitting, vc_link, source_id, scraped_at)
causelist_case  (id, bench_id, list_date, court_no, serial_no, case_ref, case_type, petitioner, respondent, advocate, pro_se, ia_numbers, section, subsection, scraped_at)
```

### Users and auth

```sql
users           (id, phone, name, email, created_at)
otp_requests    (phone, otp_hash, expires_at, attempts, created_at)
```

### Case tracking

```sql
tracked_cases   (id, user_id, case_ref, alert_serial, look_ahead, alert_active, alerted_at, created_at)
subscriptions   (id, user_id, contact_type, phone, target_serial, look_ahead, created_at)
notification_log(id, user_id, case_ref, channel, message, sent_at)
```

---

## 6. API Reference — Phase 1 Endpoints

Base URL: `http://127.0.0.1:8009` (local) / Railway URL (prod)

### Auth
```
POST /auth/send-otp        body: {phone}
POST /auth/verify-otp      body: {phone, otp}
GET  /auth/me              header: Bearer <token>
PATCH /auth/me             body: {name, email}
```

### Live board
```
GET /current-state         all courts, latest snapshot
GET /event-traces          change log; ?court_id=, ?limit=
GET /field-state/{court_id} per-field history for one court
```

### Causelist
```
GET /causelist/dates       dates with stored caselists
GET /causelist/prefixes    distinct case_ref prefixes (MAT, FMA…)
GET /causelist/search      ?case_ref=, ?advocate=, ?party=, ?judge=, ?date_from=, ?date_to=, ?side=, ?list_type=
GET /causelist/{YYYY-MM-DD} all benches and cases for a date
```

### My Cases (auth required)
```
POST   /my-cases                   track a case
GET    /my-cases                   list tracked cases
DELETE /my-cases/{case_ref}        untrack
POST   /my-cases/{case_ref}/alert  body: {alert_serial, look_ahead}
DELETE /my-cases/{case_ref}/alert  clear alert
```

### Export
```
GET /export/current-state.csv
GET /export/event-traces.csv
```

---

## 7. Data Flow Diagrams

### Live Monitor Flow
```
Playwright browser (headless)
    │ navigates to principal.php
    │ executes in-page JS → fetches display_api.json
    ▼
list[dict] — raw court rows
    │
    ▼ scraper.scrape_table_once_sync()
    │
    ▼ _build_court_id() → stable key per court
    │
    ▼ change_detector.apply_snapshot()
    │   ├── read field_state (current known values)
    │   ├── diff each field
    │   ├── write event_trace record for each changed field
    │   │     start_time = field_state.start_time
    │   │     end_time = now()
    │   │     duration_seconds = end - start
    │   └── update field_state (new value, new start_time)
    │
    ▼ update current_state (full JSON blob)
    │
    ▼ sleep ~15s, repeat
```

### Search Query Flow
```
User types in CauselistSearch.tsx
    │ debounced 300ms
    ▼
GET /causelist/search?advocate=Sharma&date_from=2026-05-01
    │
    ▼ api.py receives request
    │ builds WHERE clauses dynamically
    │
    ▼ PostgreSQL:
    │   causelist_case ILIKE '%Sharma%' on advocate column
    │   trigram index (pg_trgm) used for fuzzy match
    │   JOIN causelist_bench for judge/bench info
    │   ORDER BY list_date DESC LIMIT 100
    │
    ▼ JSON response → TanStack Query caches it
    │
    ▼ CauselistSearch.tsx renders results table
```

### Alert Delivery Flow — Phase 1 (email only)
```
Evening causelist scrape completes for tomorrow
    │
    ▼ send_causelist_alerts(tomorrow_date)
    │   JOIN tracked_cases ON causelist_case.case_ref
    │   JOIN users to get email address
    │   for each match:
    │     send email via Resend API
    │     log to notification_log (channel='email')
    │
    ▼ User receives email "Your case listed tomorrow, Court X, Serial Y"

During court hours (live monitor loop):
    │
    ▼ After each apply_snapshot():
    │   fetch tracked_cases WHERE alert_serial IS NOT NULL
    │   for each court's current serial:
    │     if serial >= (alert_serial - look_ahead):
    │       if not already alerted today:
    │         send email via Resend
    │         set alerted_at = now()

--- Phase 2 upgrade (same flow, swap delivery) ---
    replace send_email() → send_whatsapp() via MSG91
    requires: DLT template approved, MSG91_WHATSAPP_AUTH_KEY set
```

---

## 8. Phase 2 Roadmap — Technical Preview

Phase 2 features are documented in `21_COMPLETE_SYSTEM_ARCHITECTURE.md`. Summary:

### WhatsApp Alerts (moving from Phase 1)
- Same alert logic as Phase 1 email — just swap delivery channel
- MSG91 WhatsApp API: `send_whatsapp(phone, template_id, params)`
- WATI alternative if MSG91 DLT delayed
- DLT template submission: start during Phase 1 build, approval ready for Phase 2 launch
- DB: no schema changes — `notification_log.channel` already supports multiple values

### Billing System
- `matters` table — cases tracked for billing purposes
- `matter_members` — which advocates are on a matter with roles and fee splits
- `billing_entries` — per-appearance and out-of-court entries
- `invoices` — GST-compliant invoices with PDF generation (WeasyPrint)
- Auto-trigger: when live board shows case being heard, auto-create billing entry if matter exists

### Advocate Portal
- Role hierarchy: Solicitor → AOR → Senior Counsel → Junior → Clerk → Client
- Law firm accounts with shared matter access
- Enrollment number verification (Bar Council)

### Order Tracking
- Daily court order PDF scraping
- OCR extraction for image-based PDFs (Tesseract)
- Case reference matching from order text
- Link orders to causelist appearances

### Normalized ECODE Table
- `causelist_ecode` — one row per distinct section header per bench
- Eliminates header duplication per case (65% storage reduction)
- FK from `causelist_case.ecode_id` to `causelist_ecode.id`

---

## 9. Technical Questions and Open Issues

### Architecture / Design

1. **URL routing priority:** React Router adds bookmarkable URLs — should this be done before launch or can it wait? Navigation currently works but pages cannot be shared via link.

2. **Session expired UX:** Currently a 401 from the API silently breaks the page. Before launch, we need: detect 401 → clear localStorage → redirect to auth page. Estimated 2 hours.

3. **raw_text column:** `causelist_case` stores raw HTML text per case — never queried, ~25 MB/week. Should we drop this before launch to keep the DB clean? It is a safe, reversible change.

4. **jurisdiction field:** `causelist_bench.jurisdiction` stores the bench header text (jurisdiction type, hearing categories). Currently scraped and stored but not exposed in the API or frontend. Should it appear in search results or the causelist view?

### Alerts (Phase 1 — email)

5. **Alert checker location:** Serial-based alert check runs inside `run_monitor.py` after each snapshot. Low latency (fires within ~15s of threshold being crossed). Add a short-circuit: skip the DB query if no tracked cases exist in the current court.

6. **Resend API key:** Need `RESEND_API_KEY` env var set on Railway before alerts can fire. No other dependency.

7. **Email address requirement:** Users must have an email set in their profile to receive alerts. `PATCH /auth/me` covers this. Should we prompt new users to add email during onboarding?

### Alerts (Phase 2 — WhatsApp, plan now)

8. **DLT template content:** Finalize during Phase 1 build so approval is ready for Phase 2 launch:
   - Evening-before template: "Your case {case_ref} is listed tomorrow, Court {court_no}, Serial {serial_no}."
   - Serial alert template: "Court {court_no} is now at Serial {current_serial}. Your case is approaching."

9. **Provider choice:** MSG91 (already integrated for OTP) vs WATI (BSP, easier Meta approval). Recommend MSG91 for consistency — same vendor, same billing.

### Data / Performance

8. **Causelist backfill depth:** We currently have ~7 days of historical causelist data. Should we scrape further back (1 month, 3 months)? Each additional month adds ~10 MB to the DB.

9. **Supabase free tier limits:** Current size is ~50 MB for 7 days. Free tier limit is 500 MB. At current growth rate, we hit the limit in ~70 days. Plan: drop `raw_text` column first (saves ~60%) and then monitor.

10. **pg_trgm threshold:** Current trigram search on advocate name returns results where `similarity(name, query) > 0.2`. This may return too many false positives. Should we tighten to 0.3?

### Security / Production

11. **JWT_SECRET must be set before launch.** If the default secret is used in production, anyone who reads the source code can forge valid JWTs and impersonate any user. This is a blocker for go-live.

12. **Rate limiting scope:** Current OTP rate limit is 60s per phone. Should we also add a global rate limit per IP (e.g., max 10 OTP requests per IP per hour) to prevent abuse?

13. **CORS:** The API currently allows all origins in development. Before production launch, restrict `allow_origins` to the Vercel domain only.

---

*This document covers Phase 1 technical state. For the full system architecture including Phase 2+ design, see `21_COMPLETE_SYSTEM_ARCHITECTURE.md`.*  
*For the business requirements document, see `SRS_BUSINESS.md` in this folder.*

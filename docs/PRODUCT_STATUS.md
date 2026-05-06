# EventTrace — Product Status & Roadmap
> Last updated: 2026-05-05

---

## 1. What's Built (Current State)

### 1.1 Backend — Fully Working

#### Real-time Court Monitor
- Playwright scraper polls `principal.php` → fetches `display_api.json` via in-page JS
- Field-level change detector: tracks every field per court (`field_state` table)
- Emits `event_trace` records on any change (case ref, serial, VC link, etc.)
- Synthetic `__present__` field tracks courts going absent/returning
- Serial ranges compressed (`[1,2,3,15,16]` → `"1-3,15-16"`)
- VC links scraped separately (multiple windows: 0h, 6h, 8h, 20h IST)

#### Causelist Scraper
- Playwright scrapes daily cause list HTML from CHC website
- Parser extracts benches, cases, judges, advocates, IA numbers
- Scheduler runs retry windows 20:30→22:00 IST (4 attempts)
- Backfill support for historical dates
- 4 sources: appellate_static, original_static, appellate_dynamic, original_dynamic
- Stores in `causelist_bench` + `causelist_case` tables
- Supports DAILY / SPECIAL / MONTHLY list types

#### Authentication System
- Phone OTP flow (MSG91 in prod, logs OTP in dev)
- JWT (HS256, 30-day expiry)
- Rate limiting (60s cooldown per phone)
- Max 5 OTP attempts before invalidation
- `is_new_user` flag on verify response
- `PATCH /auth/me` for profile updates (name, email)

#### Case Tracking API
- `POST /my-cases` — track a case by `case_ref`
- `GET /my-cases` — list tracked cases
- `DELETE /my-cases/{case_ref}` — untrack
- `POST /my-cases/{case_ref}/alert` — set serial alert (with look-ahead)
- `DELETE /my-cases/{case_ref}/alert` — clear alert
- Per-case: court_no, bench_label, petitioner, respondent, alert_serial, look_ahead stored

#### Causelist Search API
- Full-text search by: case_ref, advocate, party/petitioner, judge
- Filters: date_from, date_to, side (APPELLATE/ORIGINAL), list_type
- PostgreSQL trigram indexes on petitioner/respondent for fast fuzzy search
- Returns: bench info + case details

#### Subscriptions / Alerts (infrastructure only — not yet firing)
- `subscriptions` table with contact_type (telegram/whatsapp), phone, target_serial, look_ahead
- `notification_log` for delivery history
- WhatsApp via Twilio webhook (`POST /webhook/whatsapp`)
- Telegram bot (`telegram_bot.py`)
- `POST /alert` endpoint to create serial-based subscriptions

#### Export
- `GET /export/current-state.csv`
- `GET /export/event-traces.csv`

---

### 1.2 Frontend — EventTrace-Web

#### Pages Built

| Page | Status | Notes |
|------|--------|-------|
| `AuthPage.tsx` | ✓ Works | Phone + OTP flow, dev mode OTP banner |
| `DisplayBoard.tsx` | ✓ Works | Live court grid, event traces, VC links, absent courts |
| `Causelist.tsx` | ✓ Works | Date picker → courts list → cases list; side/list_type filters |
| `CauselistSearch.tsx` | ✓ Works | Full search with all filters |
| `MyCases.tsx` | ✓ Built | Track/untrack cases, set serial alerts |
| `ProfilePage.tsx` | ✓ Built | Display/edit name, email, tier badge |

#### Infrastructure
- React + TypeScript + Tailwind CSS + Vite
- React Query for server state
- JWT in localStorage (`et_token`)
- Tab-based navigation (no URL routing yet)
- API client in `src/api/client.ts` — covers all endpoints
- Deployed on Vercel; API on Railway

---

## 2. What's NOT Done

### 2.1 Alert Delivery (Day 5 — Blocked by External)

**What's missing:**
- Monitor loop doesn't check `tracked_cases.alert_serial` against live serial data
- No code path: "current serial >= (alert_serial - look_ahead) → send WhatsApp/SMS"
- MSG91 WhatsApp API not wired (DLT approval pending)
- WATI/WhatsApp BSP not set up (Meta approval 24–48h)
- Email alerts: not implemented at all
- "Tomorrow's cause list" scan: no job that checks tracked cases against newly scraped causelist

**What's needed:**
1. Alert checker job (background loop or hook in monitor/scheduler)
2. MSG91 or WATI WhatsApp delivery module
3. Email delivery (SendGrid / Resend / SMTP)
4. DLT template approval from TRAI (India regulation, ~3–7 days)
5. Frontend: notification settings UI

---

### 2.2 Case History Timeline (Day 10 — Not Started)

**What's missing:**
- `case_snapshots` table: snapshot of case data per date with hash
- `case_timeline_events` table: TRACK_STARTED / NO_CHANGE / UPDATED / NOT_FOUND entries
- Daily diff job: after causelist scrape, compare each tracked case against last snapshot
- `GET /case/{case_ref}/timeline` endpoint
- Timeline UI component in MyCases

---

### 2.3 My Cases — Missing Enrichment

`GET /my-cases` needs two more fields currently missing:
- `last_seen_date` — most recent `list_date` where case_ref appeared in `causelist_case`
- `last_seen_court` — court_no on that date
- `next_hearing_date` — earliest future `list_date` in `causelist_case` for this case_ref

These are simple DB queries, not implemented in `my_cases.py` yet.

---

### 2.4 CI/CD (Day 6 — Not Started)

- No GitHub Actions workflow (lint, type-check, build)
- Vercel auto-deploys already; Railway needs wiring

---

### 2.5 UI Redesign (Not Started)

See `STITCH_PROMPT_V2.md` for the full enhanced design prompt.

---

### 2.6 Error Monitoring — Sentry (Day 11 — Not Started)

- No Sentry SDK in backend or frontend
- ~15 min setup, free tier covers 5k errors/month

---

### 2.7 Custom Domain (Day 11 — Not Started)

- Currently on `*.railway.app` and `*.vercel.app`

---

### 2.8 End-to-End Tests (Day 13 — Not Started)

- No Playwright/Cypress test suite

---

## 3. Architecture — What to Add

### 3.1 CaseSnapshot + Timeline Tables

```sql
CREATE TABLE case_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_ref     TEXT NOT NULL,
    list_date    TEXT NOT NULL,
    data_json    TEXT NOT NULL,
    hash         TEXT NOT NULL,       -- SHA256(data_json), fast diff
    created_at   TEXT NOT NULL,
    UNIQUE (case_ref, list_date)
);
CREATE INDEX idx_case_snapshots_ref  ON case_snapshots(case_ref);
CREATE INDEX idx_case_snapshots_date ON case_snapshots(list_date);

CREATE TABLE case_timeline_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    case_ref        TEXT NOT NULL,
    event_type      TEXT NOT NULL,   -- TRACK_STARTED | NO_CHANGE | UPDATED | NOT_FOUND
    event_date      TEXT NOT NULL,   -- YYYY-MM-DD
    change_summary  TEXT,            -- JSON diff, null for NO_CHANGE/TRACK_STARTED
    created_at      TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX idx_ctl_events_user_case ON case_timeline_events(user_id, case_ref);
CREATE INDEX idx_ctl_events_date      ON case_timeline_events(event_date);
```

**Daily job flow (post-causelist-scrape):**
1. For each unique tracked `case_ref` across all users
2. Look up in today's `causelist_case`
3. Not found → `NOT_FOUND` event for all users tracking it
4. Found → compute `SHA256(data_json)`, compare with last snapshot
5. Hash matches → `NO_CHANGE` event
6. Hash differs → JSON diff, `UPDATED` event + new snapshot

**New endpoints:**
- `GET /case/{case_ref}/timeline?limit=30` (auth required)
- `GET /causelist/snapshot/{case_ref}?date=YYYY-MM-DD`

---

### 3.2 Alert Checker Loop

Background loop (every ~30s inside monitor OR separate process):
1. Load `tracked_cases` where `alert_active=1` AND `alert_serial IS NOT NULL`
2. For each: fetch current serial from `current_state`
3. If `current_serial >= (alert_serial - look_ahead)` AND not alerted today:
   - Send WhatsApp/email
   - Log to `notification_log`
   - Set `alerted_at = now`

Separate job after causelist scrape:
- For each tracked case: if appears in tomorrow's list → "Your case WP/123/2026 is listed for tomorrow, Court 5, Serial 42"

---

### 3.3 URL Routing

Add React Router. Routes:
```
/               → Live Board
/causelist      → Causelist (?date= param)
/search         → Search (?q= param)
/my-cases       → My Cases
/profile        → Profile
/case/:case_ref → Case detail + timeline
```

---

### 3.4 Token Expiry UX

On 401: show "Session expired — please sign in again" toast, then redirect to auth. Currently silently breaks.

---

## 4. Notification System — Full Status

### Infrastructure Built
| Component | Status |
|-----------|--------|
| `subscriptions` table + schema | ✓ |
| `notification_log` table | ✓ |
| `POST /alert` endpoint | ✓ |
| Twilio WhatsApp webhook receiver | ✓ |
| Telegram bot | ✓ (legacy) |
| `tracked_cases` alert fields | ✓ |
| MSG91 OTP delivery (auth) | ✓ |

### Not Built
| Component | Blocker |
|-----------|---------|
| Alert checker loop | Dev work ~1 day |
| Causelist-scan alert job | Dev work ~0.5 day |
| MSG91 WhatsApp delivery | DLT approval (TRAI, 3–7 days) |
| WATI/BSP integration | Meta approval 24–48h |
| Email alerts (Resend) | Dev ~0.5 day, unblocked |
| Notification settings UI | Dev ~1 day |

### Recommended path
1. Build alert checker loop + causelist-scan job (unblocked, ~1.5 days)
2. Wire Resend email (unblocked, fast)
3. Submit MSG91 DLT template now (runs in parallel, 3–7 day wait)
4. Wire WhatsApp once approved

---

## 5. Priority Order

| # | Task | Effort | Blocker |
|---|------|--------|---------|
| 1 | Alert checker loop (serial-based) | 1 day | None |
| 2 | `case_snapshots` + timeline tables + daily diff job | 1.5 days | None |
| 3 | `GET /case/{ref}/timeline` endpoint | 0.5 day | Needs #2 |
| 4 | Enrich `/my-cases` with last_seen + next_hearing | 0.5 day | None |
| 5 | Email alerts (Resend) | 0.5 day | None |
| 6 | UI redesign (per STITCH_PROMPT_V2) | 3 days | None |
| 7 | React Router URL routing | 0.5 day | None |
| 8 | Submit MSG91 DLT WhatsApp template | 0.5 day | External 3–7 days |
| 9 | CI/CD (GitHub Actions) | 0.5 day | None |
| 10 | Sentry | 0.5 day | None |
| 11 | Wire WhatsApp once DLT approved | 1 day | Needs #8 |
| 12 | E2E tests | 2 days | None |
| 13 | Custom domain | 0.5 day | Domain purchase |
| 14 | Go live | — | All above |

---

## 6. Prod Environment Checklist

| Env Var | Status | Risk |
|---------|--------|------|
| `JWT_SECRET` | ✗ Not set — using default | **CRITICAL** — set before go-live |
| `MSG91_AUTH_KEY` | ✗ Not set | OTP won't send in prod |
| `MSG91_TEMPLATE_ID` | ✗ Not set | OTP won't send in prod |
| `DATABASE_URL` | ✓ Set | — |
| `VITE_API_URL` | ✓ Set | — |

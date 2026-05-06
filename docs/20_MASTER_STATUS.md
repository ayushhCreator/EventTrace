# EventTrace — Master Feature Status
> Last updated: 2026-05-06

---

## 1. WORKS — Backend

### Real-time Court Monitor
| Feature | Status |
|---------|--------|
| Playwright scraper → `display_api.json` (bypasses CAPTCHA) | ✓ |
| Field-level change detector (`field_state` table) | ✓ |
| `event_trace` records on every field change | ✓ |
| `__present__` synthetic field (court goes absent/returns) | ✓ |
| Serial range compression (`[1,2,3,15,16]` → `"1-3,15-16"`) | ✓ |
| VC links scraped (4 windows: 0h, 6h, 8h, 20h IST) | ✓ |
| Session cookies persisted → `.state/storage_state.json` | ✓ |

### Causelist Scraper
| Feature | Status |
|---------|--------|
| Daily HTML scrape from CHC website | ✓ |
| Parser: benches, cases, judges, advocates, IA numbers | ✓ |
| Scheduler: retry windows 20:30→22:00 IST (4 attempts) | ✓ |
| Historical backfill | ✓ |
| 4 sources: appellate_static, original_static, appellate_dynamic, original_dynamic | ✓ |
| `causelist_bench` + `causelist_case` tables | ✓ |
| DAILY / SPECIAL / MONTHLY list types | ✓ |
| `section` + `subsection` per case (GROUP-IX, PIL, TRIBUNAL etc.) | ✓ |
| `jurisdiction` field on bench (order-sheet header text) | ✓ stored, not exposed in API |

### Authentication
| Feature | Status |
|---------|--------|
| Phone OTP (MSG91 prod / logs in dev) | ✓ |
| JWT HS256, 30-day expiry | ✓ |
| Rate limit: 60s cooldown per phone | ✓ |
| Max 5 OTP attempts → invalidate | ✓ |
| `is_new_user` flag on verify response | ✓ |
| `PATCH /auth/me` (name, email) | ✓ |

### Case Tracking API
| Feature | Status |
|---------|--------|
| `POST /my-cases` — track case by `case_ref` | ✓ |
| `GET /my-cases` — list tracked cases | ✓ |
| `DELETE /my-cases/{case_ref}` | ✓ |
| `POST /my-cases/{case_ref}/alert` — serial alert + look-ahead | ✓ |
| `DELETE /my-cases/{case_ref}/alert` | ✓ |

### Causelist Search API
| Feature | Status |
|---------|--------|
| Search by: case_ref, advocate, party, judge | ✓ |
| Filters: date_from, date_to, side, list_type | ✓ |
| PostgreSQL trigram indexes on petitioner/respondent | ✓ |

### Export
| Feature | Status |
|---------|--------|
| `GET /export/current-state.csv` | ✓ |
| `GET /export/event-traces.csv` | ✓ |

### Infrastructure (built but not firing)
| Feature | Status |
|---------|--------|
| `subscriptions` table + `notification_log` | ✓ schema only |
| Twilio WhatsApp webhook receiver | ✓ receives, doesn't send |
| Telegram bot | ✓ legacy, not integrated |
| `tracked_cases.alert_serial` + `look_ahead` fields | ✓ stored, not checked |

---

## 2. WORKS — Frontend (EventTrace-Web)

| Page | Status | Notes |
|------|--------|-------|
| `AuthPage.tsx` | ✓ | Phone + OTP, dev OTP banner |
| `DisplayBoard.tsx` | ✓ | Live court grid, event traces, VC links, absent courts |
| `Causelist.tsx` | ✓ | Date picker → courts → cases; side/list_type filters |
| `CauselistSearch.tsx` | ✓ | Full search, all filters |
| `MyCases.tsx` | ✓ | Track/untrack, set serial alert |
| `ProfilePage.tsx` | ✓ | Display/edit name, email, tier badge |

**Infrastructure:** React + TypeScript + Tailwind + Vite, React Query, JWT in localStorage, deployed on Vercel.

---

## 3. DOES NOT WORK / NOT BUILT

### Alert Delivery — BLOCKED
| Missing piece | Blocker |
|---------------|---------|
| Monitor loop does NOT check `alert_serial` against live serial | Dev work ~1 day |
| No code path: serial >= (alert - look_ahead) → send message | Dev work |
| MSG91 WhatsApp delivery | DLT template approval (TRAI, 3–7 days) |
| Email alerts | Not implemented |
| "Tomorrow's causelist" scan job | Not implemented |
| Notification settings UI | Not implemented |

### Case History Timeline
| Missing | Effort |
|---------|--------|
| `case_snapshots` table | 0.5 day |
| `case_timeline_events` table | 0.5 day |
| Daily diff job (post-scrape compare) | 0.5 day |
| `GET /case/{ref}/timeline` endpoint | 0.5 day |
| Timeline UI in MyCases | 1 day |

### My Cases — Missing Data
| Field | Status |
|-------|--------|
| `last_seen_date` (most recent list_date for case_ref) | Not implemented |
| `last_seen_court` | Not implemented |
| `next_hearing_date` (earliest future list_date) | Not implemented |

### Other Missing
| Feature | Status |
|---------|--------|
| URL routing (React Router) | Not started |
| 401 → "Session expired" UX (currently silently breaks) | Not started |
| CI/CD (GitHub Actions) | Not started |
| Sentry error monitoring | Not started |
| Custom domain | Not started |
| E2E tests (Playwright/Cypress) | Not started |
| UI redesign (see `STITCH_PROMPT_V2.md`) | Not started |

### Prod Env — Critical Gaps
| Var | Status | Risk |
|-----|--------|------|
| `JWT_SECRET` | NOT SET — using default | **CRITICAL before go-live** |
| `MSG91_AUTH_KEY` | Not set | OTP won't send in prod |
| `MSG91_TEMPLATE_ID` | Not set | OTP won't send in prod |
| `DATABASE_URL` | Set (Supabase Postgres) | OK |
| `VITE_API_URL` | Set | OK |

---

## 4. RESEARCH — New Features to Add

### 4.1 Billing System

**Background**: Law firms need to bill clients in two ways:
- **OUT_OF_COURT** — drafting, research, client meetings
- **IN_COURT** — appearance fees (per hearing date / court / serial)

**Role hierarchy** (determines who approves what):
```
Client
  └── Solicitor / Advocate on Record   ← approves billing, sees all
        └── Senior Counsel             (optional)
              └── Counsel              (optional)
                    └── Junior Counsel (optional)
        └── Clerk                      ← logs entries
```

**New tables needed:**

```sql
CREATE TABLE matters (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,        -- "Sharma vs State of WB"
  case_ref    TEXT,                 -- links to causelist_case.case_ref
  created_by  TEXT REFERENCES users(id),
  created_at  TEXT NOT NULL
);

CREATE TABLE matter_members (
  matter_id   TEXT REFERENCES matters(id),
  user_id     TEXT REFERENCES users(id),
  role        TEXT NOT NULL,        -- SOLICITOR | ADVOCATE_ON_RECORD | SENIOR_COUNSEL | COUNSEL | JUNIOR_COUNSEL | CLERK | CLIENT
  fee_share   REAL,                 -- % split (Splitwise-style)
  PRIMARY KEY (matter_id, user_id)
);

CREATE TABLE billing_entries (
  id           TEXT PRIMARY KEY,
  matter_id    TEXT REFERENCES matters(id),
  billed_by    TEXT REFERENCES users(id),
  entry_type   TEXT NOT NULL,       -- IN_COURT | OUT_OF_COURT
  description  TEXT,
  amount       REAL NOT NULL,
  currency     TEXT NOT NULL DEFAULT 'INR',
  entry_date   TEXT NOT NULL,
  court_date   TEXT,                -- IN_COURT only
  court_no     TEXT,                -- IN_COURT only
  case_ref     TEXT,                -- IN_COURT only
  approved_by  TEXT REFERENCES users(id),
  approved_at  TEXT,
  created_at   TEXT NOT NULL
);

CREATE TABLE matter_invites (
  id             TEXT PRIMARY KEY,
  matter_id      TEXT REFERENCES matters(id),
  invited_email  TEXT NOT NULL,
  role           TEXT NOT NULL,
  invited_by     TEXT REFERENCES users(id),
  accepted_at    TEXT,
  created_at     TEXT NOT NULL
);
```

**API routes:**
```
POST /matters                      — create matter
GET  /matters                      — my matters
POST /matters/{id}/members         — add member by phone/email
POST /matters/{id}/billing         — add entry
GET  /matters/{id}/billing         — list entries
GET  /matters/{id}/billing/summary — Splitwise-style per-role breakdown
POST /matters/{id}/invite          — email invite (cross-firm)
```

**Causelist integration**: IN_COURT entry creation → auto-fill court_date + court_no from `causelist_case` if `case_ref` is tracked.

**Dashboard**: Splitwise-style — shows each matter, total billed, per-member share, pending approvals. Email used for cross-firm invite.

---

### 4.2 Bench Header / Order-Sheet Mapping

**Problem**: The cause list PDF has a bench "header" (first page per court) listing jurisdiction, types of matters, order-sheet categories. Users want to search by this header and see it mapped to each case.

**Current state**:
- `causelist_bench.jurisdiction` — already stores the header text block (extracted between last HON'BLE line and VC link)
- `causelist_case.section` / `.subsection` — already captures in-bench category headers (e.g., "GROUP - IX", "PIL")
- `bench_id` FK already maps every case to its bench header

**What's missing**:
1. `jurisdiction` not returned in `GET /causelist/{date}` or search API responses
2. No search filter for bench jurisdiction/category

**Fix (small):**
- Add `jurisdiction` + `bench_label` + `judges` to the causelist search response JSON
- Add optional `section=` filter to `/causelist/search`

---

### 4.3 Data Size Problem

**Problem**: 45–50 MB for 6–7 days of scraping.

**Root cause**: `causelist_case.raw_text` column — stores raw text block per case. Never queried. Pure debug data.

**Fix**: Remove `raw_text` from DB writes in `causelist_parser.py` → `upsert_causelist()`. Keep it in logs if debugging needed.

**Estimated saving**: ~60–70% of case table size.

---

## 5. Priority Queue

| # | Task | Effort | Blocker |
|---|------|--------|---------|
| 1 | Set `JWT_SECRET` in Railway prod | 5 min | **CRITICAL** |
| 2 | Drop `raw_text` from DB writes | 1h | None |
| 3 | Expose `jurisdiction` in causelist/search API | 2h | None |
| 4 | Alert checker loop (serial-based) | 1 day | None |
| 5 | `case_snapshots` + timeline tables + daily diff job | 1.5 days | None |
| 6 | Enrich `/my-cases` with last_seen + next_hearing | 0.5 day | None |
| 7 | `matters` + `matter_members` + `billing_entries` schema | 1 day | None |
| 8 | Billing API routes | 1 day | Needs #7 |
| 9 | Billing UI (Splitwise-style dashboard) | 2 days | Needs #8 |
| 10 | Email invite (Resend) | 0.5 day | Needs #7 |
| 11 | React Router URL routing | 0.5 day | None |
| 12 | 401 → session expired UX | 2h | None |
| 13 | Submit MSG91 DLT WhatsApp template | 0.5 day | External 3–7 days |
| 14 | UI redesign (STITCH_PROMPT_V2) | 3 days | None |
| 15 | CI/CD (GitHub Actions) | 0.5 day | None |
| 16 | Sentry | 0.5 day | None |
| 17 | E2E tests | 2 days | None |
| 18 | Custom domain | 0.5 day | Domain purchase |

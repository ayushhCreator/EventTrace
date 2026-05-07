# EventTrace — Product Status
> Last updated: 2026-05-05 | Status: **Ready for testing**

---

## What's Built & Merged

### Auth + Users
- [x] Phone OTP login (MSG91 in prod, dev_otp in dev)
- [x] JWT tokens (30-day, signed with `JWT_SECRET`)
- [x] `GET /auth/me` + `PATCH /auth/me` — profile read/update
- [x] JWT_SECRET guard — raises `RuntimeError` at startup if default secret + prod env vars detected
- [x] `GET /auth/notification-settings` — per-user prefs
- [x] `PATCH /auth/notification-settings` — update prefs (whatsapp / email / serial_alerts / causelist_alerts / change_alerts)

### Case Tracking (`/my-cases`)
- [x] `POST /my-cases` — track a case; emits `TRACK_STARTED` timeline event
- [x] `GET /my-cases` — list with enrichment: `last_seen_date`, `last_seen_court`, `next_hearing_date` (live join on `causelist_case`)
- [x] `DELETE /my-cases/{case_ref}` — untrack
- [x] `POST /my-cases/{case_ref}/alert` — set serial proximity alert
- [x] `DELETE /my-cases/{case_ref}/alert` — clear alert

### Timeline System
- [x] `case_snapshots` table — SHA256-hashed causelist rows per case per date
- [x] `case_timeline_events` table — per-user audit log (TRACK_STARTED / NO_CHANGE / UPDATED / NOT_FOUND / case_in_causelist)
- [x] `GET /case/{case_ref}/timeline?limit=50` — JWT-gated, returns stats + event list
  - Stats: `days_tracked`, `times_appeared`, `changes_detected`
  - Full diff for UPDATED events: `{changed: [{field, old, new}]}`

### Daily Case Diff Job (`services/case_diff.py`)
- [x] `run_daily_case_diff(db, date)` — runs after each successful causelist scrape
  - Fetches all tracked case_refs from DB
  - Looks up each in `causelist_case` for that date
  - SHA256 diff against last snapshot → NOT_FOUND / NO_CHANGE / UPDATED event per user
- [x] `run_causelist_alert_scan(db, date)` — fires `case_in_causelist` alert when case appears
  - Deduped per user per date

### Serial Alert Checker (`services/alert_checker.py`)
- [x] `check_serial_alerts(db, snapshot)` — called after every monitor poll (~15s)
  - Checks `tracked_cases` with `alert_active=1`, matches `court_no` to live board row
  - Fires when `current_serial >= alert_serial - look_ahead`
  - Deduped by `alerted_at` column (once per day per case)

### Notification Delivery (`services/notifications.py`)
- [x] `send_alert(db, tracked_case, alert_type, context)` — unified delivery
  - Priority 1: WATI WhatsApp (`WATI_API_KEY`)
  - Priority 2: MSG91 WhatsApp (`MSG91_WHATSAPP_KEY`)
  - Fallback: logs as `pending_approval` in `notification_log`
  - Secondary: Email via Resend (`RESEND_API_KEY`) if user has email set
- [x] `send_email_alert(to_email, subject, body_html)` — standalone Resend mailer
- [x] Alert types: `serial_reached`, `case_in_causelist`, `case_updated`
- [x] All alerts respect per-user `notification_prefs`

### Causelist
- [x] 4 sources: appellate static, original static, dropdown (SB/DB), monthly
- [x] Parallel backfill on startup
- [x] `side` + `list_type` filters on all endpoints
- [x] `GET /causelist/search` — full text search by case_ref / advocate / party / judge

### Monitor
- [x] Playwright scraper polling every ~15s
- [x] Change detection + `event_trace` log
- [x] Serial alert delivery (legacy subscriptions table + new tracked_cases)
- [x] Adjournment notifications + 15-min reminder
- [x] VC Zoom link scraping

### DB Schema
- [x] SQLite (WAL) + Postgres backends — same public interface
- [x] Non-destructive migrations (`ALTER TABLE ADD COLUMN IF NOT EXISTS`)
- [x] New tables: `case_snapshots`, `case_timeline_events`
- [x] New columns: `tracked_cases.alerted_at`, `users.notification_prefs`, `notification_log.tracked_case_id`, `notification_log.status`

### Frontend (EventTrace-Web)
- [x] Live board — real-time court status
- [x] Cause list browser with side/list_type filters
- [x] Case search (by ref, advocate, party, judge, date range)
- [x] **My Cases** — tracked cases with:
  - `last_seen_date` / `last_seen_court` / `next_hearing_date` shown per card
  - Timeline drawer (slide-in panel) with stats + full event history + diff view
  - Serial alert set/edit/clear
- [x] **Profile + Notification Settings** — name/email edit + 5 alert toggles (with live toggle UI)
- [x] API client: `getCaseTimeline`, `getNotificationSettings`, `updateNotificationSettings`

---

## Environment Variables Needed for Full Prod

| Variable | Purpose | Required |
|---|---|---|
| `JWT_SECRET` | Token signing | **Yes — will crash at startup without it if DATABASE_URL is set** |
| `DATABASE_URL` | Postgres DSN | Yes (prod) |
| `MSG91_AUTH_KEY` | OTP delivery | Yes (prod) |
| `MSG91_TEMPLATE_ID` | OTP template | Yes (prod) |
| `WATI_API_KEY` | WhatsApp alerts (primary) | Optional |
| `MSG91_WHATSAPP_KEY` | WhatsApp alerts (fallback) | Optional |
| `RESEND_API_KEY` | Email alerts | Optional |
| `RESEND_FROM_EMAIL` | From address | Optional (default: alerts@eventtrace.in) |
| `TELEGRAM_TOKEN` | Legacy Telegram bot | Optional |
| `ADMIN_CHAT_ID` | Scrape failure alerts | Optional |

---

## What Needs Testing

### Backend
- [ ] `ensure_schema()` on fresh Postgres — all new tables created cleanly
- [ ] `ensure_schema()` on existing prod Postgres — column migrations apply without errors
- [ ] `GET /my-cases` returns `last_seen_date` / `last_seen_court` / `next_hearing_date` correctly
- [ ] `POST /my-cases` creates `TRACK_STARTED` event in `case_timeline_events`
- [ ] `GET /case/{case_ref}/timeline` — correct stats, events newest-first
- [ ] `run_daily_case_diff` — UPDATED event generated when causelist row changes
- [ ] `run_daily_case_diff` — NOT_FOUND event when case absent from list
- [ ] `run_causelist_alert_scan` — alert fires and dedupes correctly (no double-fire same date)
- [ ] `check_serial_alerts` — fires when `current_serial >= alert_serial - look_ahead`
- [ ] `check_serial_alerts` — does NOT fire twice same day (`alerted_at` guard)
- [ ] `send_alert` — WATI delivery with valid key
- [ ] `send_alert` — falls back to MSG91 when WATI key absent
- [ ] `send_alert` — logs `pending_approval` when no WhatsApp provider configured
- [ ] `send_email_alert` — Resend delivery with valid key; skips cleanly without key
- [ ] `GET /auth/notification-settings` — returns full defaults for new user
- [ ] `PATCH /auth/notification-settings` — persists partial updates, merges with defaults
- [ ] JWT_SECRET guard — raises `RuntimeError` on startup if `DATABASE_URL` set + default secret

### Frontend
- [ ] My Cases card shows `last_seen_date`, `last_seen_court`, `next_hearing_date`
- [ ] Next hearing date shows in green when future date exists
- [ ] Timeline drawer opens per case, shows stats + events
- [ ] UPDATED events show field diff (old → new) in red/green
- [ ] Profile page — notification toggles load correctly
- [ ] Toggling a pref saves immediately (optimistic update), persists on reload
- [ ] All 5 toggle types work independently

---

## Known Gaps / Next Steps

1. **MSG91 WhatsApp `integrated_number`** in `notifications.py` line ~89 is a placeholder — replace with real approved sender number before enabling live alerts
2. **WATI template name** `hearing_alert` must match an approved template in the WATI dashboard
3. **Email templates** are plain `<p>text</p>` — add proper HTML for better UX
4. **No push notifications** (FCM/APNs) — WhatsApp + email only for now
5. **No URL routing** — browser back/forward doesn't navigate pages; React Router not wired
6. **Token expiry UX** — 401 shows blank state; add "Session expired, please log in again" message
7. **CI/CD** — no GitHub Actions yet; Vercel auto-deploys frontend, Railway deploys manually

# Notification System — SuperSahayak Legal

## Overview

WhatsApp-first notification system built on a Postgres outbox queue. No Redis. All state lives in the DB.

---

## Architecture

```
User Action / Cron                   DB Queue                    WhatsApp
─────────────────────────────        ──────────────              ──────────────
causelist scanner          ──┐
case diff worker           ──┼──▶  enqueue_notification()  ──▶  notification_queue
monitor serial alerts      ──┘       (notification_log            ──────────────
display board triggers      ──        status="queued")         retry_worker (daemon)
                                                                  │
                                                                  ├─ WATI primary
                                                                  └─ MSG91 fallback
```

The `retry_worker` runs as a daemon thread inside `chd-run-monitor`. It polls `notification_queue` every 10s using `SELECT FOR UPDATE SKIP LOCKED` (Postgres-safe for multiple workers).

---

## Trigger Types

| Trigger | When it fires | Dedup window |
|---|---|---|
| `case_in_causelist` | Case appears in today's cause list (nightly scan ~20:30–22:00 IST) | 24h |
| `serial_reached` | Live board serial reaches case serial minus look-ahead buffer | None (fast-moving) |
| `display_board_active` | Live board serial reaches or passes case serial exactly | 4h |
| `hearing_date_changed` | Cause list diff detects next_date/hearing_date field changed | 24h |
| `judge_changed` | Cause list diff detects presiding_officer/bench field changed | 24h |
| `order_uploaded` | Cause list diff detects order/judgment field changed | 24h |
| `status_changed` | Cause list diff detects any other field changed | 24h |

---

## Data Flow

### 1. Case-in-Causelist (nightly)

```
causelist_scheduler.py
  └─▶ run_causelist_alert_scan(db, date)   [case_diff.py]
        for each tracked case_ref:
          search_causelist_cases()
          enqueue_notification(db, user_id, case_ref, "case_in_causelist", ctx)
```

### 2. Serial / Display Board (live, every ~15s)

```
run_monitor.py poll loop
  └─▶ check_serial_alerts(db, snapshot)   [alert_checker.py]
  └─▶ check_display_board_triggers(db, snapshot)   [alert_checker.py]
        list_active_case_alerts(court_no, today)
        if current_serial >= alert_serial - look_ahead:  → serial_reached
        if current_serial >= alert_serial:               → display_board_active
```

### 3. Case Diff (daily, after causelist scrape)

```
causelist_scheduler.py
  └─▶ run_daily_case_diff(db, date)   [case_diff.py]
        for each tracked case_ref:
          compare old snapshot vs new row
          _send_change_alerts() → classifies fields →
            hearing_date_changed / judge_changed / order_uploaded / status_changed
          enqueue_notification() for each trigger type detected
```

### 4. Dispatch (daemon, every 10s)

```
notification_retry_worker.py  run_retry_worker(db)
  claim_queued_notifications(batch=20)   ← SELECT FOR UPDATE SKIP LOCKED
  for each item:
    _dispatch_queue_item(db, item)
      wa_number = user.whatsapp_number or user.phone
      _send_wati(wa_number, message, key)       ← primary
      _send_msg91_whatsapp(wa_number, message)  ← fallback
    ack_queue_item(success=True)   → delete queue row, update log status="sent"
    ack_queue_item(success=False)  → exponential backoff; delete after 3 attempts
```

---

## Pre-send Checks (enqueue_notification)

In order — if any check fails, notification is dropped silently:

1. `trigger_type` in known set
2. User exists in DB
3. `alert_preference.enabled == True` (default: True)
4. Not in quiet hours (per user preference)
5. User has a WhatsApp number (verified or not)
6. Daily cap not exceeded (`daily_wa_cap`, default 100/day)
7. Dedup key not seen within window (24h for most triggers, 0 for serial_reached)

---

## DB Tables

| Table | Purpose |
|---|---|
| `notification_log` | Append-only record of every notification attempt |
| `notification_queue` | Outbox queue — rows claimed by worker, deleted on success |
| `alert_preferences` | Per-user, per-case, per-trigger settings (channel, enabled, quiet hours) |
| `whatsapp_otps` | OTP codes for WA number verification |
| `search_log` | Audit log of case searches by logged-in users |

---

## API Endpoints

### User-facing

| Method | Path | Description |
|---|---|---|
| `GET` | `/notifications` | Paginated notification history. Params: `limit`, `offset`, `unread_only`, `case_ref` |
| `GET` | `/notifications/unread-count` | Badge count |
| `POST` | `/notifications/{id}/mark-read` | Mark one read |
| `POST` | `/notifications/mark-all-read` | Mark all read |
| `POST` | `/auth/whatsapp/send-otp` | Send OTP to WhatsApp number |
| `POST` | `/auth/whatsapp/verify-otp` | Verify OTP, set `whatsapp_verified=1` |
| `GET` | `/my-cases/{case_ref}/notification-prefs` | Get 7 trigger prefs for a case |
| `PUT` | `/my-cases/{case_ref}/notification-prefs` | Bulk update prefs |
| `PATCH` | `/my-cases/{case_ref}/notification-prefs/{trigger_type}` | Update single trigger pref |

### Admin (requires `is_admin=1`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/stats/notifications?days=7` | Breakdown by status / channel / trigger |
| `GET` | `/admin/stats/users` | Total users, WA-verified count |
| `GET` | `/admin/stats/searches?limit=20` | Top search queries |

### Webhooks (delivery receipts)

| Method | Path | Provider |
|---|---|---|
| `POST` | `/webhook/wati/delivery` | WATI status callbacks |
| `POST` | `/webhook/msg91/delivery` | MSG91 delivery reports |

---

## Environment Variables

```env
# MSG91 WhatsApp (primary for this deployment)
MSG91_AUTH_KEY=your_msg91_auth_key
MSG91_WHATSAPP_NUMBER=91XXXXXXXXXX     # sender number, no + prefix

# WATI (alternative primary — code tries this first if key present)
WATI_API_KEY=your_wati_bearer_token

# Email (Resend)
RESEND_API_KEY=your_resend_key
RESEND_FROM_EMAIL=alerts@supersahayak.in

# Webhook security (optional)
WATI_WEBHOOK_SECRET=your_hmac_secret

# JWT (already set)
JWT_SECRET=your_jwt_secret
```

---

## MSG91 Setup

1. Log in to [msg91.com](https://msg91.com) → WhatsApp section
2. Register / connect your WhatsApp Business number
3. Create **one** template:
   - **Name**: `hearing_alert`
   - **Category**: UTILITY
   - **Language**: English (`en`)
   - **Body**: `{{1}}`
   - No header, no footer, no buttons
4. Submit for Meta approval (typically a few hours for UTILITY)
5. Once approved, set in `.env` or GCP env vars:
   ```
   MSG91_AUTH_KEY=xxxxx
   MSG91_WHATSAPP_NUMBER=91XXXXXXXXXX
   ```
6. Optional delivery webhooks: MSG91 dashboard → Webhook → URL:
   ```
   https://your-domain/webhook/msg91/delivery
   ```

---

## User Flow

```
User signs up
  → sees phone input field
  → hint text below field: "Please enter your WhatsApp number to receive case alerts"
  → enters phone (same number used for WhatsApp)
  → receives SMS OTP via MSG91
  → OTP verified → JWT issued
  → phone auto-saved as whatsapp_number, whatsapp_verified = true

  → user tracks a case
  → tomorrow: case in causelist → WhatsApp alert sent to same number via MSG91
  → day of hearing: serial alert → WhatsApp alert sent via MSG91
```

> **One number, one OTP.** Phone number = WhatsApp number. No second verification step.
> MSG91 (`MSG91_AUTH_KEY`) handles SMS OTP delivery.

---

## Limits

- Default daily WA cap: **100 notifications/user/day** (configurable per user via `daily_wa_cap` column)
- Max tracked cases: **unlimited**
- Notification queue retry: **3 attempts**, exponential backoff (10s → 20s → 40s)
- Queue poll interval: **10 seconds**
- Dedup: **24h** for most triggers, **none** for `serial_reached`

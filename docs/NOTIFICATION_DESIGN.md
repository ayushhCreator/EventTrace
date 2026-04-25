# Notification System — Design & Problem Log

**Date:** 2026-04-24  
**Status:** Implemented

---

## Problems Being Solved

### Problem 1 — Wrong-day notification (the date bug)

**What happened:**  
A lawyer sets a watch for case serial 11 in Room 8 *for tomorrow's hearing*.  
Today's board also happens to show Room 8 at serial 11 (or higher).  
The notification fires *today*, which is wrong — the lawyer has no hearing today.

**Root cause:**  
The `subscriptions` table had no `hearing_date` column.  
`_dispatch_notifications` checked all active subscriptions against the live board regardless of which day the subscription was meant for.

**Fix:**  
Added `hearing_date TEXT` (YYYY-MM-DD IST) to `subscriptions`.  
- Default: today's date at time of subscription creation.  
- Bot `/watch` command accepts optional date arg: `/watch 8 11 5 2026-04-25`.  
- Web form has a date picker (default today, can pick tomorrow).  
- `_dispatch_notifications` filters: `hearing_date = today_ist OR hearing_date IS NULL`.  
  NULL = legacy rows created before this migration (treated as any-day, backward compatible).

---

### Problem 2 — Missed alert on monitor restart (Bug B2)

**What happened:**  
Monitor crashes / restarts mid-day.  
Court serial jumps from 195 to 210 while monitor was down.  
Lawyer's case is serial 205, look_ahead = 5, so alert threshold = 200.  
When monitor comes back, it sees serial 210 — above threshold.  
But `was_notified_today(sub_id)` returns `False` (notification log is empty for today).  
**Wait — this means the notification DOES fire correctly on restart?**

Actually yes — Bug B2 was about the *opposite*: notification fires today, then monitor restarts, `was_notified_today` returns `True` (log entry exists), so if the serial changed further and re-triggers, it won't re-fire. That part was correct.

The real variant of B2: `was_notified_today` was keyed to UTC date, not IST date. A notification sent at 23:45 IST (= 18:15 UTC) is logged as UTC date. On the next IST day (after 00:00 IST), `was_notified_today` checks UTC date again and may skip because UTC day hasn't rolled over yet. Edge case, ~90-minute window.

**Fix:**  
Replaced `was_notified_today` with `last_notified_serial` column on the subscription row.  
Logic:
```
FIRE if:
  current_serial >= alert_threshold
  AND (last_notified_serial IS NULL OR current_serial > last_notified_serial)

After firing:
  UPDATE subscriptions SET last_notified_serial = current_serial WHERE id = ?
```

This is date-agnostic and restart-safe. If monitor restarts and re-checks the same serial, `current_serial == last_notified_serial` → no duplicate. If serial advances further, `current_serial > last_notified_serial` → fires again (useful for courts that run very long).

Since subscriptions now have `hearing_date`, each day's subscription is a fresh row — `last_notified_serial` starts as NULL every time a lawyer sets a new watch.

---

### Problem 3 — No web-based alert signup

**What happened:**  
Lawyers had to find and use the Telegram bot to set an alert. Many lawyers don't use Telegram.

**Fix:**  
Added `POST /alert` API endpoint.  
Added alert modal to the UI — bell button (🔔) on each court row.  
Form fields:
- Room (pre-filled, read-only)
- Your serial number
- Date (date picker, default today)
- Alert N serials before (default 5)
- Display name (optional)

On submit: stored in `subscriptions` table with `contact_type = 'web'`.  
Notification delivery for web signups: pending WhatsApp/email integration.  
Fallback shown in modal: pre-filled Telegram bot command to copy.

---

## Schema Changes

```sql
ALTER TABLE subscriptions ADD COLUMN hearing_date TEXT;
-- YYYY-MM-DD IST. NULL = legacy (any-day). New rows always have a date.

ALTER TABLE subscriptions ADD COLUMN contact_type TEXT NOT NULL DEFAULT 'telegram';
-- 'telegram' | 'web' | 'whatsapp' (future)

ALTER TABLE subscriptions ADD COLUMN last_notified_serial INTEGER;
-- Replaces was_notified_today() check. NULL = not yet notified.

ALTER TABLE subscriptions ADD COLUMN display_name TEXT;
-- Optional human name for web signups.
```

Migration is non-destructive: all columns added via `ALTER TABLE … ADD COLUMN` inside `ensure_schema`, wrapped in try/except to handle re-runs on existing DBs.

---

## Notification Dispatch Logic (updated)

```python
def _dispatch_notifications(snapshot, db, settings):
    today_str = _today_ist().isoformat()
    subs = db.list_active_subscriptions(today=today_str)
    # ↑ filters: active=1 AND (hearing_date IS NULL OR hearing_date = today_str)

    for sub in subs:
        room_no = str(sub["room_no"])
        target = int(sub["target_serial"])
        look_ahead = int(sub["look_ahead"])
        alert_threshold = target - look_ahead
        last_notified = sub.get("last_notified_serial")  # may be None

        current_serial = _get_current_serial_for_room(snapshot, room_no)
        if current_serial is None:
            continue

        should_fire = (
            current_serial >= alert_threshold
            and (last_notified is None or current_serial > last_notified)
        )

        if should_fire:
            _send_alert(sub, current_serial, vc_links, settings, db)
            db.update_last_notified_serial(sub["id"], current_serial)
            db.log_notification(sub["id"], payload_json)
```

---

## Bot Command Changes

```
/watch <room> <serial>                    → today, look_ahead=5
/watch <room> <serial> <ahead>            → today, custom look_ahead
/watch <room> <serial> <ahead> <date>     → specific date (YYYY-MM-DD)

Examples:
/watch 8 205              → alert when room 8 hits 200 today
/watch 8 11 3 2026-04-25  → alert when room 8 hits 8, for tomorrow's hearing
```

`/list` now shows the `hearing_date` for each active alert.

---

## Web Alert Flow

```
1. Lawyer opens https://eventtrace.in/ui
2. Sees live board
3. Clicks 🔔 on Room 8 row
4. Modal opens:
     Room: 8 (locked)
     Your serial: [____]
     Date: [2026-04-24] (date picker)
     Alert before: [5]
     Name (optional): [____]
     [ Set Alert ]
     ─────────────────────────────────
     Or use Telegram bot:
     /watch 8 <serial> 5 <date>  [Copy]
5. "Set Alert" → POST /alert → stored in DB
   (notification delivery pending Telegram link or WhatsApp)
```

---

## Files Changed

| File | Change |
|------|--------|
| `src/eventtrace/db.py` | Schema migration, updated `add_subscription`, new `update_last_notified_serial`, filtered `list_active_subscriptions` |
| `src/eventtrace/run_monitor.py` | `_dispatch_notifications` — date filter + `last_notified_serial` logic |
| `src/eventtrace/telegram_bot.py` | `/watch` date arg, `/list` shows date |
| `src/eventtrace/api.py` | `POST /alert` endpoint |
| `src/eventtrace/ui/index.html` | Bell button per row, alert modal |

---

## What Is NOT Done Yet

- WhatsApp delivery for web signups (Phase 2)
- Telegram account linking from web (user enters `@username` and bot confirms) (Phase 4)
- Email delivery (not planned)
- Push notifications / PWA (Phase 4)
- Daily digest (separate feature, Phase 2)

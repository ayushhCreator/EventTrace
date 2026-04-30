from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .causelist_scraper import scrape_and_store_vc_links
from .change_detector import apply_snapshot
from .config import Settings
from .db import get_db, utc_now

log = logging.getLogger(__name__)

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _today_ist() -> date:
    return _now_ist().date()


def _build_court_id(row: dict[str, Any], key_fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for f in key_fields:
        v = row.get(f)
        if v is None:
            continue
        parts.append(str(v))
    if parts:
        return " | ".join(parts)
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _compress_ranges(nums: list[int]) -> str:
    """[15,16,29,31,33] → '15-16,29,31,33'"""
    if not nums:
        return ""
    nums = sorted(set(nums))
    parts: list[str] = []
    start = end = nums[0]
    for n in nums[1:]:
        if n == end + 1:
            end = n
        else:
            parts.append(str(start) if start == end else f"{start}-{end}")
            start = end = n
    parts.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(parts)


def _aggregate_rows(
    rows: list[dict[str, Any]], key_fields: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Group raw API rows by court_id; aggregate cause_list_sr_no as range string."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        court_id = _build_court_id(row, key_fields)
        groups.setdefault(court_id, []).append(row)

    snapshot: dict[str, dict[str, Any]] = {}
    for court_id, court_rows in groups.items():
        base = dict(court_rows[-1])
        serials: list[int] = []
        for r in court_rows:
            try:
                serials.append(int(r["cause_list_sr_no"]))
            except (KeyError, TypeError, ValueError):
                pass
        if serials:
            base["cause_list_sr_no"] = _compress_ranges(serials)
        snapshot[court_id] = base
    return snapshot


# ── VC Scrape scheduler ──────────────────────────────────────────────────────
# Scrape windows (IST hour, inclusive): 0, 6, 8, 20
# Each date is scraped at most once per window; stores {date_str: set_of_hours_done}
_vc_scrape_lock = threading.Lock()
_vc_scraped: dict[str, set[int]] = {}  # {"2026-04-23": {0, 6, 8}}

_VC_WINDOWS = [0, 6, 8, 20]  # IST hours that trigger a scrape


def _should_scrape_vc(for_date: date, current_ist_hour: int) -> bool:
    date_str = for_date.isoformat()
    past_windows = [h for h in _VC_WINDOWS if h <= current_ist_hour]
    if not past_windows:
        return False
    with _vc_scrape_lock:
        done = _vc_scraped.get(date_str, set())
        return bool(set(past_windows) - done)


def _mark_vc_scraped(for_date: date, window_hour: int) -> None:
    date_str = for_date.isoformat()
    with _vc_scrape_lock:
        _vc_scraped.setdefault(date_str, set()).add(window_hour)


def _run_vc_scrape(for_date: date, window_hour: int, settings: Settings, db: Any) -> None:
    try:
        links = scrape_and_store_vc_links(for_date, settings, db)
        _mark_vc_scraped(for_date, window_hour)
        log.info("VC scrape for %s (window %02d:00): %d links", for_date, window_hour, len(links))
    except Exception as exc:
        log.warning("VC scrape failed for %s: %s", for_date, exc)


def _vc_scheduler_thread(settings: Settings, db: Any) -> None:
    """Background thread: triggers VC scrapes at the 4 daily windows."""
    while True:
        try:
            now_ist = _now_ist()
            today = now_ist.date()
            hour = now_ist.hour
            tomorrow = today + timedelta(days=1)

            # Scrape today's links at windows 0, 6, 8
            for w in [0, 6, 8]:
                if hour >= w and _should_scrape_vc(today, w):
                    _run_vc_scrape(today, w, settings, db)
                    break  # one scrape per wake-up is enough

            # At 14:00+ IST scrape tomorrow's links (cause list usually published by afternoon)
            if hour >= 14 and _should_scrape_vc(tomorrow, 14):
                _run_vc_scrape(tomorrow, 14, settings, db)

        except Exception as exc:
            log.warning("VC scheduler error: %s", exc)

        time.sleep(1800)  # check every 30 minutes


# ── Notification helpers ──────────────────────────────────────────────────────

def _wa_creds_ok(settings: Settings) -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_from)


def _send_wa(settings: Settings, phone: str, body: str) -> None:
    from .whatsapp_bot import send_whatsapp_sync
    send_whatsapp_sync(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_whatsapp_from,
        to_phone=phone,
        body=body,
    )


def _send_tg(settings: Settings, telegram_id: str, body: str) -> None:
    import httpx
    httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
        json={"chat_id": telegram_id, "text": body, "parse_mode": "Markdown"},
        timeout=10,
    ).raise_for_status()


def _deliver(sub: dict, body: str, settings: Settings) -> None:
    contact_type = sub.get("contact_type", "telegram")
    if contact_type == "whatsapp":
        phone = sub.get("phone", "")
        if not phone or not _wa_creds_ok(settings):
            return
        _send_wa(settings, phone, body)
    elif contact_type == "telegram":
        tid = sub.get("telegram_id", "")
        if not tid or not settings.telegram_token:
            return
        _send_tg(settings, tid, body)


def _current_serial_for_room(snapshot: dict[str, dict[str, Any]], room_no: str) -> int | None:
    best: int | None = None
    for row in snapshot.values():
        if str(row.get("room_no", "")) != room_no:
            continue
        try:
            val = int(str(row.get("cause_list_sr_no", "")).split("-")[-1])
            if best is None or val > best:
                best = val
        except (TypeError, ValueError):
            pass
    return best


# ── Fix 1: Monitor scrape-failure notifications ───────────────────────────────
_FAILURE_NOTIFY_THRESHOLD = 5   # consecutive failures before warning
_failure_outage_notified = False  # only notify once per outage


def _notify_monitor_down(db: Any, settings: Settings) -> None:
    today_str = _today_ist().isoformat()
    subs = db.list_active_subscriptions(today=today_str)
    for sub in subs:
        try:
            body = (
                "⚠️ *EventTrace monitor is having trouble*\n"
                f"Scraping has been failing for the last ~{_FAILURE_NOTIFY_THRESHOLD * settings.poll_seconds}s.\n"
                "Board data may be stale — check the cause list directly.\n"
                "Your alert is still active and will fire once monitoring resumes."
            )
            _deliver(sub, body, settings)
        except Exception as exc:
            log.warning("monitor-down notify failed for sub %s: %s", sub["id"], exc)


# ── Fix 2: Court adjournment notifications ────────────────────────────────────

def _notify_adjournments(
    changes: list, snapshot: dict[str, dict[str, Any]], db: Any, settings: Settings
) -> None:
    """Detect courts that just left the board; notify subscribers whose serial wasn't reached."""
    today_str = _today_ist().isoformat()

    # Build court_id → room_no map from current_state
    court_to_room: dict[str, str] = {}
    for state in db.list_current_state():
        room = str((state.get("data") or {}).get("room_no", "")).strip()
        if room:
            court_to_room[state["court_id"]] = room

    for change in changes:
        if change.field_name != "__present__" or change.new_value != "0":
            continue
        room_no = court_to_room.get(change.court_id, "")
        if not room_no:
            continue

        last_serial = _current_serial_for_room(snapshot, room_no)
        subs = db.list_active_subscriptions_for_room(room_no, today_str)

        for sub in subs:
            target = int(sub["target_serial"])
            alerted = sub.get("alerted_at")
            # Only notify if alert never fired (serial never reached threshold)
            if alerted:
                continue
            try:
                serial_str = f"Board stopped at serial *{last_serial}*." if last_serial else ""
                body = (
                    f"🏛 *Court Room {room_no} has adjourned*\n"
                    f"Your case serial *{target}* was not reached today.\n"
                    f"{serial_str}\n\n"
                    "Check the official cause list for rescheduling."
                )
                _deliver(sub, body, settings)
                db.deactivate_subscription(sub["id"])
                log.info("Adjournment notified: sub %s room %s target %d", sub["id"], room_no, target)
            except Exception as exc:
                log.warning("Adjournment notify failed sub %s: %s", sub["id"], exc)


# ── Fix 3: Missed-alert reminder ─────────────────────────────────────────────
_REMINDER_DELAY_SECONDS = 15 * 60  # 15 minutes after alert fired


def _send_reminders(
    snapshot: dict[str, dict[str, Any]], db: Any, settings: Settings
) -> None:
    """If alert fired >15 min ago and serial has passed target, send reminder."""
    today_str = _today_ist().isoformat()
    subs = db.list_active_subscriptions(today=today_str)
    now = utc_now()

    for sub in subs:
        alerted_at_str = sub.get("alerted_at")
        if not alerted_at_str:
            continue
        if sub.get("reminder_sent"):
            continue

        try:
            alerted_at = datetime.fromisoformat(alerted_at_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        elapsed = (now - alerted_at).total_seconds()
        if elapsed < _REMINDER_DELAY_SECONDS:
            continue

        room_no = str(sub["room_no"])
        target = int(sub["target_serial"])
        current_serial = _current_serial_for_room(snapshot, room_no)

        if current_serial is None or current_serial < target:
            continue  # case not yet called

        try:
            body = (
                f"⚠️ *Reminder — Court Room {room_no}*\n"
                f"Serial is now at *{current_serial}* — your case was *{target}*.\n"
                "Your case may have already been called.\n"
                "Please check with the court immediately."
            )
            _deliver(sub, body, settings)
            db.mark_reminder_sent(sub["id"])
            log.info("Reminder sent: sub %s room %s serial %d", sub["id"], room_no, current_serial)
        except Exception as exc:
            log.warning("Reminder failed sub %s: %s", sub["id"], exc)


# ── Alert dispatch ────────────────────────────────────────────────────────────

def _dispatch_notifications(
    snapshot: dict[str, dict[str, Any]], db: Any, settings: Settings
) -> None:
    today_str = _today_ist().isoformat()
    subs = db.list_active_subscriptions(today=today_str)
    if not subs:
        return

    vc_links = db.get_vc_zoom_links(today_str)

    for sub in subs:
        room_no = str(sub["room_no"])
        target = int(sub["target_serial"])
        look_ahead = int(sub["look_ahead"])
        alert_threshold = target - look_ahead

        # Fire only once — skip if already alerted
        if sub.get("alerted_at"):
            continue

        current_serial = _current_serial_for_room(snapshot, room_no)
        if current_serial is None:
            continue

        if current_serial < alert_threshold:
            continue

        zoom_url = vc_links.get(room_no, "")
        payload = {
            "room_no": room_no,
            "current_serial": current_serial,
            "target_serial": target,
            "zoom_url": zoom_url,
        }
        try:
            contact_type = sub.get("contact_type", "telegram")
            if contact_type == "telegram":
                if not sub.get("telegram_id") or not settings.telegram_token:
                    continue
                from .telegram_bot import send_notification_sync
                send_notification_sync(
                    token=settings.telegram_token,
                    telegram_id=sub["telegram_id"],
                    payload=payload,
                )
            elif contact_type == "whatsapp":
                if not sub.get("phone") or not _wa_creds_ok(settings):
                    log.warning("Twilio creds not set — skipping WhatsApp sub %s", sub["id"])
                    continue
                from .whatsapp_bot import _build_alert_message
                _send_wa(settings, sub["phone"], _build_alert_message(payload))
            else:
                continue

            db.update_last_notified_serial(sub["id"], current_serial)
            db.mark_alerted(sub["id"])   # Fix 3: track when alert fired
            db.log_notification(sub["id"], json.dumps(payload))
            log.info(
                "Notified [%s] %s: room %s serial %d (target %d)",
                contact_type, sub.get("telegram_id") or sub.get("phone"), room_no, current_serial, target,
            )
        except Exception as exc:
            log.warning("Notification failed for sub %s: %s", sub["id"], exc)


# ── Main loop ────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    db = get_db(settings)
    db.ensure_schema()

    from .scraper import scrape_table_once_sync

    print(f"Monitoring {settings.url}")
    db_label = settings.database_url or settings.db_path
    print(f"DB: {db_label}")
    print(f"Poll seconds: {settings.poll_seconds}")

    # Start VC scrape scheduler in background
    vc_thread = threading.Thread(
        target=_vc_scheduler_thread, args=(settings, db), daemon=True, name="vc-scheduler"
    )
    vc_thread.start()
    log.info("VC scrape scheduler started")

    consecutive_failures = 0

    while True:
        observed = utc_now()
        try:
            rows = scrape_table_once_sync(settings)
            snapshot = _aggregate_rows(rows, settings.key_fields)

            changes = apply_snapshot(
                db,
                snapshot_by_court=snapshot,
                observed_time=observed,
                ignore_fields=settings.key_fields,
            )
            for c in changes:
                log.info(
                    "%s %s: %r -> %r (%ds)",
                    c.court_id, c.field_name, c.old_value, c.new_value, c.duration_seconds,
                )

            # Fix 1: reset failure counter on success
            consecutive_failures = 0
            global _failure_outage_notified
            _failure_outage_notified = False
            db.set_monitor_state("last_successful_poll", observed.isoformat())
            db.set_monitor_state("board_active", "1" if rows else "0")

            _dispatch_notifications(snapshot, db, settings)           # alert fire
            _notify_adjournments(changes, snapshot, db, settings)     # Fix 2: adjournment
            _send_reminders(snapshot, db, settings)                   # Fix 3: reminder

        except KeyboardInterrupt:
            raise
        except Exception as e:
            log.warning("scrape/apply failed: %s", e)
            consecutive_failures += 1

            # Fix 1: notify subscribers after sustained failure during court hours
            ist_hour = _now_ist().hour
            if (
                consecutive_failures >= _FAILURE_NOTIFY_THRESHOLD
                and 8 <= ist_hour <= 17
                and not _failure_outage_notified
            ):
                try:
                    _notify_monitor_down(db, settings)
                    _failure_outage_notified = True
                except Exception as notify_exc:
                    log.warning("monitor-down notification failed: %s", notify_exc)

        time.sleep(settings.poll_seconds)

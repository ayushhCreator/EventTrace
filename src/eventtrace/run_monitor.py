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
from .db import DB, utc_now

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


def _run_vc_scrape(for_date: date, window_hour: int, settings: Settings, db: DB) -> None:
    try:
        links = scrape_and_store_vc_links(for_date, settings, db)
        _mark_vc_scraped(for_date, window_hour)
        log.info("VC scrape for %s (window %02d:00): %d links", for_date, window_hour, len(links))
    except Exception as exc:
        log.warning("VC scrape failed for %s: %s", for_date, exc)


def _vc_scheduler_thread(settings: Settings, db: DB) -> None:
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

            # At 20:00+ IST scrape tomorrow's links
            if hour >= 20 and _should_scrape_vc(tomorrow, 20):
                _run_vc_scrape(tomorrow, 20, settings, db)

        except Exception as exc:
            log.warning("VC scheduler error: %s", exc)

        time.sleep(1800)  # check every 30 minutes


# ── Telegram notification dispatch ──────────────────────────────────────────

def _dispatch_notifications(
    snapshot: dict[str, dict[str, Any]], db: DB, settings: Settings
) -> None:
    """Check active subscriptions and send Telegram alerts when serial is close."""
    if not settings.telegram_token:
        return
    try:
        from .telegram_bot import send_notification_sync
    except ImportError:
        return

    subs = db.list_active_subscriptions()
    if not subs:
        return

    today_str = _today_ist().isoformat()
    vc_links = db.get_vc_zoom_links(today_str)

    for sub in subs:
        if db.was_notified_today(sub["id"]):
            continue

        room_no = str(sub["room_no"])
        target = int(sub["target_serial"])
        look_ahead = int(sub["look_ahead"])

        # Find current max serial for this room
        current_serial: int | None = None
        for row in snapshot.values():
            if str(row.get("room_no", "")) == room_no:
                try:
                    sr = row.get("cause_list_sr_no", "")
                    # May be a range like "15-16"; take the upper bound
                    parts = str(sr).split("-")
                    val = int(parts[-1])
                    if current_serial is None or val > current_serial:
                        current_serial = val
                except (TypeError, ValueError):
                    pass

        if current_serial is None:
            continue

        if current_serial >= target - look_ahead:
            zoom_url = vc_links.get(room_no, "")
            payload = {
                "room_no": room_no,
                "current_serial": current_serial,
                "target_serial": target,
                "zoom_url": zoom_url,
            }
            try:
                send_notification_sync(
                    token=settings.telegram_token,
                    telegram_id=sub["telegram_id"],
                    payload=payload,
                )
                db.log_notification(sub["id"], json.dumps(payload))
                log.info(
                    "Notified %s: room %s serial %d (target %d)",
                    sub["telegram_id"], room_no, current_serial, target,
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
    db = DB(settings.db_path)
    db.ensure_schema()

    from .scraper import scrape_table_once_sync

    print(f"Monitoring {settings.url}")
    print(f"DB: {settings.db_path}")
    print(f"Poll seconds: {settings.poll_seconds}")

    # Start VC scrape scheduler in background
    vc_thread = threading.Thread(
        target=_vc_scheduler_thread, args=(settings, db), daemon=True, name="vc-scheduler"
    )
    vc_thread.start()
    log.info("VC scrape scheduler started")

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

            _dispatch_notifications(snapshot, db, settings)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            log.warning("scrape/apply failed: %s", e)

        time.sleep(settings.poll_seconds)

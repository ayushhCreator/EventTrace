"""Causelist daily scheduler with retry logic.

Schedule (IST): attempt at 20:30, 21:00, 21:30, 22:00.
Stop as soon as one attempt succeeds.
If all four fail: log error + Telegram alert, sleep until next day.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

# Four attempt windows (IST HH:MM), 30 min apart
_WINDOWS_IST = ["20:30", "21:00", "21:30", "22:00"]


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _seconds_until(hhmm: str, ref: datetime) -> float:
    """Seconds from ref until today's hhmm (IST). Negative if already past."""
    h, m = map(int, hhmm.split(":"))
    target = ref.replace(hour=h, minute=m, second=0, microsecond=0)
    return (target - ref).total_seconds()


def _next_window_after_now() -> tuple[str | None, float]:
    """Return (window_str, seconds_to_wait) for the next window after now.

    Returns (None, seconds_to_tomorrow_first_window) if all windows are past.
    """
    now = _now_ist()
    for w in _WINDOWS_IST:
        secs = _seconds_until(w, now)
        if secs > 0:
            return w, secs
    # All past — return time until tomorrow's first window
    tomorrow = now.date() + timedelta(days=1)
    h, m = map(int, _WINDOWS_IST[0].split(":"))
    next_day = datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, tzinfo=_IST)
    return None, (next_day - now).total_seconds()


def _already_scraped(db: Any, for_date: date) -> bool:
    try:
        return for_date.isoformat() in db.list_causelist_dates()
    except Exception:
        return False


def _telegram_alert(settings: Any, message: str) -> None:
    """Send Telegram message to admin if TELEGRAM_TOKEN + ADMIN_CHAT_ID set."""
    admin_chat_id = getattr(settings, "admin_chat_id", None)
    if not settings.telegram_token or not admin_chat_id:
        log.warning("No admin_chat_id configured — skipping Telegram alert")
        return
    try:
        import httpx
        httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
            json={"chat_id": admin_chat_id, "text": f"[EventTrace] {message}"},
            timeout=10,
        )
    except Exception as exc:
        log.error("Telegram alert failed: %s", exc)


def _attempt_scrape(db: Any, for_date: date) -> bool:
    """Fetch, parse, store. Returns True on success."""
    from .causelist_parser import fetch_causelist_html, parse_causelist

    log.info("Scraping causelist for %s ...", for_date)
    try:
        html = fetch_causelist_html(for_date)
        if not html:
            log.warning("No HTML returned for %s", for_date)
            return False
        parsed = parse_causelist(html, for_date)
        n = db.store_causelist(parsed)
        log.info("Stored %d cases across %d courts for %s", n, len(parsed), for_date)
        return True
    except Exception as exc:
        log.error("Scrape failed: %s", exc)
        return False


def _sleep_until_tomorrow(settings: Any, for_date: date) -> None:
    """Alert + sleep until tomorrow's first window."""
    msg = f"Causelist scrape FAILED for {for_date} — all 4 retry windows exhausted."
    log.error(msg)
    _telegram_alert(settings, msg)

    _, secs = _next_window_after_now()
    secs = max(60.0, secs)
    log.info("Sleeping %.0f min until next day's first window.", secs / 60)
    time.sleep(secs)


def run_scheduler(settings: Any, db: Any) -> None:
    """Main loop — runs forever, scraping daily cause list with retries."""
    log.info("Causelist scheduler started. Windows (IST): %s", ", ".join(_WINDOWS_IST))

    while True:
        now = _now_ist()
        today = now.date()

        # Already have today's data — sleep until tomorrow's first window
        if _already_scraped(db, today):
            _, secs = _next_window_after_now()
            # If we're past all today's windows, secs is time until tomorrow — correct.
            # If we're before today's windows, sleep until first window is still correct
            # (we'll re-check and find it scraped again).
            secs = max(60.0, secs)
            log.info("Already have %s. Sleeping %.0f min.", today, secs / 60)
            time.sleep(secs)
            continue

        now_hhmm = now.strftime("%H:%M")

        # Before the first window — wait
        if now_hhmm < _WINDOWS_IST[0]:
            next_w, secs = _next_window_after_now()
            secs = max(60.0, secs)
            log.info("Before first window. Sleeping %.0f min until %s IST.", secs / 60, next_w)
            time.sleep(secs)
            continue

        # After last window and still not scraped — all windows exhausted
        if now_hhmm > _WINDOWS_IST[-1]:
            _sleep_until_tomorrow(settings, today)
            continue

        # We're in the window range — attempt scrape
        success = _attempt_scrape(db, today)
        if success:
            continue  # loop will detect already_scraped and sleep until tomorrow

        # Failed — find next window
        next_w, secs = _next_window_after_now()
        if next_w is None:
            # No more windows today
            _sleep_until_tomorrow(settings, today)
        else:
            secs = max(60.0, secs)
            log.info("Scrape failed. Next attempt at %s IST (%.0f min).", next_w, secs / 60)
            time.sleep(secs)


def main() -> None:
    """CLI entry point: chd-schedule-causelist"""
    import logging as _logging
    from .config import Settings
    from .db import get_db

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = Settings()
    db = get_db(settings)
    db.ensure_schema()
    run_scheduler(settings, db)

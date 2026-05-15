"""Causelist daily scheduler with retry logic.

Two scrape passes per day:
  Evening (20:30–22:00 IST): fetch next working day's list as soon as published.
  Morning (08:30–09:30 IST): re-scrape TODAY's list — courts often revise overnight.

The morning pass always overwrites, ensuring users see the final revised version
rather than whatever was published the previous evening.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

import structlog

from ..common.time import IST, ist_now
from ..core.health import start_health_server

log = structlog.get_logger()

_WINDOWS_IST = ["20:30", "21:00", "21:30", "22:00"]
_MORNING_WINDOWS_IST = ["08:30", "09:00", "09:30"]


def _now_ist() -> datetime:
    return ist_now()


def _seconds_until(hhmm: str, ref: datetime) -> float:
    h, m = map(int, hhmm.split(":"))
    target = ref.replace(hour=h, minute=m, second=0, microsecond=0)
    return (target - ref).total_seconds()


def _next_window_after_now() -> tuple[str | None, float]:
    now = _now_ist()
    for w in _WINDOWS_IST:
        secs = _seconds_until(w, now)
        if secs > 0:
            return w, secs
    tomorrow = now.date() + timedelta(days=1)
    h, m = map(int, _WINDOWS_IST[0].split(":"))
    next_day = datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, m, tzinfo=IST)
    return None, (next_day - now).total_seconds()


def _next_working_day(from_date: date) -> date:
    """Next calendar day, skipping weekends (court closed Sat/Sun)."""
    d = from_date + timedelta(days=1)
    while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        d += timedelta(days=1)
    return d


def _source_already_scraped(
    db: Any, for_date: date, source_id: str, schedule: str = "daily"
) -> bool:
    """True if this source already has data for the relevant period."""
    try:
        if schedule == "monthly":
            # Monthly: check if any day in this calendar month is already stored
            year, month = for_date.year, for_date.month
            for day in range(1, 8):
                try:
                    candidate = date(year, month, day)
                except ValueError:
                    break
                if candidate.weekday() < 5:
                    if db.is_causelist_source_scraped(candidate.isoformat(), source_id):
                        return True
            return False
        return db.is_causelist_source_scraped(for_date.isoformat(), source_id)
    except AttributeError:
        return for_date.isoformat() in db.list_causelist_dates()
    except Exception:
        return False


def _store_result(db: Any, result: Any, scraped_at: datetime | None = None) -> int:
    """Persist a SourceResult to DB. Returns number of cases stored."""
    return db.store_causelist(result.courts, scraped_at=scraped_at)


def _telegram_alert(settings: Any, message: str) -> None:
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


def _attempt_all_sources(
    db: Any,
    target_date: date,
    sources: list[Any],
    pending: set[str],
) -> set[str]:
    """Run all pending sources. Returns set of source_ids that succeeded."""
    succeeded: set[str] = set()
    for source in sources:
        if source.source_id not in pending:
            continue
        log.info("[%s] scraping %s ...", source.source_id, target_date)
        result = source.fetch(target_date)
        if result.ok:
            n = _store_result(db, result)
            log.info(
                "[%s] stored %d cases (%d courts) for %s",
                source.source_id,
                n,
                len(result.courts),
                target_date,
            )
            succeeded.add(source.source_id)
            _run_case_diff_jobs(db, target_date.isoformat())
        else:
            log.warning(
                "[%s] no data for %s: %s", source.source_id, target_date, result.error or "empty"
            )
    return succeeded


def _run_case_diff_jobs(db: Any, date_str: str) -> None:
    try:
        from ..services.case_diff import run_daily_case_diff, run_causelist_alert_scan

        run_daily_case_diff(db, date_str)
        run_causelist_alert_scan(db, date_str)
    except Exception as exc:
        log.warning("case_diff jobs failed for %s: %s", date_str, exc)


def _is_working_day(d: date) -> bool:
    return d.weekday() < 5


def _morning_rescrape(db: Any, target_date: date, sources: list[Any]) -> None:
    """Force re-scrape today's daily causelists — court may have revised overnight."""
    daily_sources = [s for s in sources if getattr(s, "_cfg", None) and
                     getattr(s._cfg, "schedule", "daily") == "daily"]
    if not daily_sources:
        return
    log.info("Morning re-scrape: force-refreshing %d source(s) for %s", len(daily_sources), target_date)
    for source in daily_sources:
        log.info("[%s] morning re-scrape %s", source.source_id, target_date)
        result = source.fetch(target_date)
        if result.ok:
            n = _store_result(db, result)
            log.info("[%s] morning re-scrape stored %d cases for %s", source.source_id, n, target_date)
            _run_case_diff_jobs(db, target_date.isoformat())
        else:
            log.warning("[%s] morning re-scrape failed for %s: %s", source.source_id, target_date, result.error or "empty")


def _sleep_until_tomorrow(settings: Any, failed_ids: set[str], target_date: date) -> None:
    msg = (
        f"Causelist scrape FAILED for {target_date} — all 4 windows exhausted. "
        f"Sources still missing: {', '.join(sorted(failed_ids))}"
    )
    log.error(msg)
    _telegram_alert(settings, msg)
    _, secs = _next_window_after_now()
    secs = max(60.0, secs)
    log.info("Sleeping %.0f min until next day's first window.", secs / 60)
    time.sleep(secs)


def run_scheduler(settings: Any, db: Any) -> None:
    """Main loop — runs forever, scraping all registered sources each day."""
    from .registry import build_sources

    sources = build_sources()
    log.info(
        "Causelist scheduler started. Sources: %s. Evening windows (IST): %s. Morning re-scrape: %s",
        [s.source_id for s in sources],
        ", ".join(_WINDOWS_IST),
        ", ".join(_MORNING_WINDOWS_IST),
    )

    morning_rescraped_date: date | None = None  # track so we only re-scrape once per day

    while True:
        now = _now_ist()
        today = now.date()
        now_hhmm = now.strftime("%H:%M")

        # ── Morning re-scrape pass (08:30–09:30 IST, working days only) ──────
        # Courts often revise their causelists overnight. Re-fetch today's list
        # to overwrite yesterday's stale evening scrape with the final version.
        if (
            _is_working_day(today)
            and _MORNING_WINDOWS_IST[0] <= now_hhmm <= _MORNING_WINDOWS_IST[-1]
            and morning_rescraped_date != today
        ):
            _morning_rescrape(db, today, sources)
            morning_rescraped_date = today
            time.sleep(60)
            continue

        # ── Evening scrape pass: fetch next working day's list ────────────────
        target_date = _next_working_day(today)

        # Compute which sources still need scraping for target_date.
        # Skip sources whose schedule doesn't apply (monthly only in first week).
        pending = {
            s.source_id
            for s in sources
            if s.should_run_for(target_date)
            and not _source_already_scraped(
                db,
                target_date,
                s.source_id,
                schedule=getattr(getattr(s, "_cfg", None), "schedule", "daily"),
            )
        }

        if not pending:
            _, secs = _next_window_after_now()
            secs = max(60.0, secs)
            log.info("All sources done for %s. Sleeping %.0f min.", target_date, secs / 60)
            time.sleep(secs)
            continue

        if now_hhmm < _WINDOWS_IST[0]:
            next_w, secs = _next_window_after_now()
            secs = max(60.0, secs)
            log.info("Before first window. Sleeping %.0f min until %s IST.", secs / 60, next_w)
            time.sleep(secs)
            continue

        if now_hhmm > _WINDOWS_IST[-1]:
            _sleep_until_tomorrow(settings, pending, target_date)
            continue

        # In window — attempt all pending sources
        log.info("Window open. Attempting %d pending source(s) for %s.", len(pending), target_date)
        succeeded = _attempt_all_sources(db, target_date, sources, pending)
        pending -= succeeded

        if not pending:
            continue  # all done — next iteration sleeps until tomorrow

        next_w, secs = _next_window_after_now()
        if next_w is None:
            _sleep_until_tomorrow(settings, pending, target_date)
        else:
            secs = max(60.0, secs)
            log.info(
                "%d source(s) still pending. Next attempt at %s IST (%.0f min): %s",
                len(pending),
                next_w,
                secs / 60,
                sorted(pending),
            )
            time.sleep(secs)


def main() -> None:
    """CLI entry point: chd-schedule-causelist"""
    from ..core.logging_setup import configure_logging
    from ..config import Settings
    from ..db import get_db

    configure_logging()
    start_health_server()
    settings = Settings()
    db = get_db(settings)
    db.ensure_schema()
    run_scheduler(settings, db)

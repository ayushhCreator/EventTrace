"""Backfill last N days of causelist data into DB.

Usage:
  chd-backfill          # last 7 days
  chd-backfill --days 14
"""

from __future__ import annotations

import structlog
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any

log = structlog.get_logger()

_FETCH_WORKERS = 6  # parallel HTTP fetches


def _ist_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()


def _last_n_workdays(n: int) -> list[date]:
    """Return up to n weekdays going back from today (IST), inclusive."""
    days: list[date] = []
    d = _ist_today()
    while len(days) < n:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d)
        d -= timedelta(days=1)
    return days


def _fetch_one(source: Any, for_date: date) -> Any:
    """Fetch one (source, date) pair. Returns SourceResult."""
    log.info("[%s] fetching %s …", source.source_id, for_date)
    return source.fetch(for_date)


def backfill_causelist(days: int = 7) -> None:
    from .registry import build_sources
    from .causelist_scheduler import _source_already_scraped
    from ..config import Settings
    from ..db import get_db

    settings = Settings()
    db = get_db(settings)

    sources = build_sources()
    targets = _last_n_workdays(days)

    # Build list of (source, date) pairs that need fetching
    work = []
    for source in sources:
        sched = getattr(getattr(source, "_cfg", None), "schedule", "daily")
        for for_date in targets:
            if not source.should_run_for(for_date):
                continue
            if _source_already_scraped(db, for_date, source.source_id, schedule=sched):
                log.info("[%s] %s already scraped — skip", source.source_id, for_date)
                continue
            work.append((source, for_date))

    if not work:
        log.info("Backfill: nothing to fetch")
        return

    log.info("Backfill: %d (source, date) pairs to fetch (workers=%d)", len(work), _FETCH_WORKERS)

    # Group work by date — process one day at a time to bound memory usage.
    # Each day: fetch all sources in parallel, store immediately, then free RAM.
    from itertools import groupby
    work_by_date: dict[date, list[Any]] = {}
    for src, d in work:
        work_by_date.setdefault(d, []).append(src)

    for for_date in sorted(work_by_date):
        day_sources = work_by_date[for_date]
        log.info("Backfill: fetching %d sources for %s", len(day_sources), for_date)

        day_results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            futures = {pool.submit(_fetch_one, src, for_date): src for src in day_sources}
            for future in as_completed(futures):
                src = futures[future]
                try:
                    day_results[src.source_id] = future.result()
                except Exception as exc:
                    log.error("[%s] %s fetch exception: %s", src.source_id, for_date, exc)

        # Store immediately, then release day results from memory
        for src in day_sources:
            result = day_results.get(src.source_id)
            if result is None:
                continue
            if not result.ok:
                log.warning(
                    "[%s] no data for %s: %s", src.source_id, for_date, result.error or "empty"
                )
                continue
            n = db.store_causelist(result.courts)
            log.info(
                "[%s] stored %d cases (%d courts) for %s",
                src.source_id,
                n,
                len(result.courts),
                for_date,
            )
        day_results.clear()


def main() -> None:
    from ..core.logging_setup import configure_logging

    configure_logging()
    args = sys.argv[1:]
    days = 7
    if "--days" in args:
        idx = args.index("--days")
        days = int(args[idx + 1])
    backfill_causelist(days)
    log.info("Backfill complete.")

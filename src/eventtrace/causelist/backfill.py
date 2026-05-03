"""Backfill last N days of causelist data into DB.

Usage:
  chd-backfill          # last 7 days
  chd-backfill --days 14
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _ist_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()


def _last_n_workdays(n: int) -> list[date]:
    """Return up to n weekdays going back from yesterday (IST)."""
    days: list[date] = []
    d = _ist_today() - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d)
        d -= timedelta(days=1)
    return days


def backfill_causelist(days: int = 7) -> None:
    from .causelist_parser import fetch_causelist_html, parse_causelist
    from ..config import Settings
    from ..db import get_db

    settings = Settings()
    db = get_db(settings)
    db.ensure_schema()

    existing = set(db.list_causelist_dates())
    targets = [d for d in _last_n_workdays(days) if d.isoformat() not in existing]

    if not targets:
        log.info("Backfill: all %d days already in DB", days)
        return

    log.info("Backfill: fetching %d missing dates: %s", len(targets), [str(d) for d in targets])

    for for_date in targets:
        log.info("Fetching causelist for %s …", for_date)
        html = fetch_causelist_html(for_date)
        if not html:
            log.warning("No causelist available for %s — skipping", for_date)
            continue
        parsed = parse_causelist(html, for_date)
        db.store_causelist(parsed)
        total_cases = sum(len(c["cases"]) for c in parsed)
        log.info("Stored %d cases (%d courts) for %s", total_cases, len(parsed), for_date)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = sys.argv[1:]
    days = 7
    if "--days" in args:
        idx = args.index("--days")
        days = int(args[idx + 1])
    backfill_causelist(days)
    log.info("Backfill complete.")

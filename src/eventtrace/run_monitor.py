from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from .change_detector import apply_snapshot
from .config import Settings
from .db import DB, utc_now
from .scraper import scrape_table_once_sync


def _build_court_id(row: dict[str, Any], key_fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for f in key_fields:
        v = row.get(f)
        if v is None:
            continue
        parts.append(str(v))
    if parts:
        return " | ".join(parts)
    # fallback: stable-ish JSON
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
        # Use last row as the representative (most recent in the list)
        base = dict(court_rows[-1])
        # Collect all serial numbers, compress into range string
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


def main() -> None:
    settings = Settings()
    db = DB(settings.db_path)
    db.ensure_schema()

    print(f"Monitoring {settings.url}")
    print(f"DB: {settings.db_path}")
    print(f"Poll seconds: {settings.poll_seconds}")

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
                print(
                    f"[{observed.isoformat()}] {c.court_id} {c.field_name}: "
                    f"{c.old_value!r} -> {c.new_value!r} ({c.duration_seconds}s)"
                )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[{observed.isoformat()}] scrape/apply failed: {e!r}")

        time.sleep(settings.poll_seconds)


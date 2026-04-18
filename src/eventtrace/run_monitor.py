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
            snapshot: dict[str, dict[str, Any]] = {}
            for row in rows:
                court_id = _build_court_id(row, settings.key_fields)
                snapshot[court_id] = row

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


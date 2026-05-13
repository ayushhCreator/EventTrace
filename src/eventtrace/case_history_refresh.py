"""Background refresh job for cached eCourts case history."""

from __future__ import annotations

import os
import time
from typing import Any

import structlog

from .config import Settings
from .db import get_db
from .routes.ecourts_test import _do_case_history

log = structlog.get_logger()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def refresh_cases(db: Any, api_key: str, limit: int | None, delay_s: float) -> None:
    rows = db.list_tracked_cases_for_refresh(limit)
    if not rows:
        log.info("case_history_refresh: no tracked cases to refresh")
        return

    log.info("case_history_refresh: refreshing %d cases", len(rows))
    for row in rows:
        try:
            cino = str(row.get("cino") or "").strip()
            state_cd = str(row.get("state_cd") or "").strip()
            court_code = str(row.get("court_code") or "").strip()
            case_type_id = str(row.get("case_type_id") or "").strip()
            case_no = str(row.get("case_no") or "").strip()
            case_year = str(row.get("case_year") or "").strip()
            if not all([cino, state_cd, court_code, case_type_id, case_no, case_year]):
                continue

            result = _do_case_history(
                state_cd=state_cd,
                court_code=court_code,
                case_type_id=case_type_id,
                case_no=case_no,
                year=case_year,
                target_cino=cino,
                api_key=api_key,
            )
            db.set_case_history_cache(
                cino=cino,
                state_cd=state_cd,
                court_code=court_code,
                case_type_id=case_type_id,
                case_no=case_no,
                case_year=case_year,
                data=result,
            )
        except Exception as exc:
            log.warning("case_history_refresh failed: %s", exc)
        if delay_s > 0:
            time.sleep(delay_s)


def main() -> None:
    settings = Settings()
    db = get_db(settings)
    db.ensure_schema()

    api_key = getattr(settings, "anthropic_api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set")

    limit_raw = os.getenv("CASE_HISTORY_REFRESH_LIMIT", "").strip()
    limit = int(limit_raw) if limit_raw else None
    delay_s = float(os.getenv("CASE_HISTORY_REFRESH_DELAY", "0.5"))

    refresh_cases(db, api_key, limit, delay_s)


if __name__ == "__main__":
    main()

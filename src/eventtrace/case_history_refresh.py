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


def _extract_next_hearing(data: dict) -> str:
    """Pull Next Hearing Date from case_status dict."""
    cs = data.get("case_status") or {}
    for key in ("Next Hearing Date", "next_hearing_date", "NextHearingDate"):
        if cs.get(key):
            return str(cs[key]).strip()
    return ""


def _notify_users(
    db: Any,
    user_ids: list[str],
    case_refs: list[str],
    trigger_type: str,
    context: dict,
) -> None:
    from .services.notification_dispatch import enqueue_notification

    for user_id in user_ids:
        case_ref = case_refs[0] if case_refs else ""
        # Use the user's own case_ref if available
        for cr in case_refs:
            tracked = db.get_tracked_case(user_id, cr)
            if tracked:
                case_ref = cr
                break
        enqueue_notification(db, user_id, case_ref, trigger_type, {**context, "case_ref": case_ref})


def refresh_cases(db: Any, api_key: str, limit: int | None, delay_s: float) -> None:
    # Use distinct cases (one CAPTCHA solve per cino, not per user)
    try:
        rows = db.list_distinct_ecourts_cases()
    except AttributeError:
        # Fallback to old method if postgres not updated yet
        rows = db.list_tracked_cases_for_refresh(limit)

    if not rows:
        log.info("case_history_refresh: no tracked cases to refresh")
        return

    if limit is not None:
        rows = rows[:limit]

    log.info("case_history_refresh: refreshing %d distinct cases", len(rows))

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

            user_ids: list[str] = list(row.get("user_ids") or [])
            case_refs: list[str] = list(row.get("case_refs") or [])
            if not user_ids:
                # Fallback: single-user row from old list_tracked_cases_for_refresh
                uid = str(row.get("user_id") or "").strip()
                cr = str(row.get("case_ref") or "").strip()
                if uid:
                    user_ids = [uid]
                if cr:
                    case_refs = [cr]

            # Snapshot old data before refresh
            old_data = db.get_case_history_cache(cino, state_cd, court_code)
            old_next_hearing = _extract_next_hearing(old_data) if old_data else ""
            old_orders_count = len((old_data or {}).get("orders") or [])

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

            new_next_hearing = _extract_next_hearing(result)
            new_orders_count = len(result.get("orders") or [])
            new_orders: list[dict] = result.get("orders") or []

            log.info(
                "case_history_refresh: refreshed %s hearing=%s orders=%d",
                cino, new_next_hearing, new_orders_count,
            )

            if not user_ids:
                continue

            # Notify: next hearing date changed
            if new_next_hearing and new_next_hearing != old_next_hearing:
                _notify_users(
                    db, user_ids, case_refs,
                    "hearing_date_changed",
                    {
                        "old_date": old_next_hearing or "unknown",
                        "new_date": new_next_hearing,
                        "cino": cino,
                    },
                )
                log.info("case_history_refresh: hearing date changed %s → %s for %s", old_next_hearing, new_next_hearing, cino)

            # Notify: new orders uploaded
            if new_orders_count > old_orders_count:
                for order in new_orders[old_orders_count:]:
                    order_date = order.get("order_date") or order.get("date") or ""
                    judge = order.get("judge") or ""
                    summary = f"by {judge}" if judge else ""
                    _notify_users(
                        db, user_ids, case_refs,
                        "order_uploaded",
                        {
                            "date": order_date,
                            "summary": summary,
                            "cino": cino,
                            "order_no": order.get("order_no") or order.get("sl_no") or "",
                        },
                    )
                log.info("case_history_refresh: %d new orders for %s", new_orders_count - old_orders_count, cino)

        except Exception as exc:
            log.warning("case_history_refresh failed for %s: %s", row.get("cino", "?"), exc)

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

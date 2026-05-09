"""Serial alert checker for tracked_cases — called after each monitor snapshot."""

from __future__ import annotations

import structlog
from typing import Any

from ..common.time import ist_today_str

log = structlog.get_logger()


def _current_serial_from_row(row: dict) -> int | None:
    raw = row.get("cause_list_sr_no")
    if raw is None:
        return None
    try:
        # May be "15-16" range string — take the last (highest)
        return int(str(raw).split("-")[-1])
    except (TypeError, ValueError):
        return None


def check_serial_alerts(db: Any, current_snapshot: list[dict]) -> None:
    today = ist_today_str()

    try:
        active_courts = db.get_courts_with_active_case_alerts(today)
    except Exception as exc:
        log.warning("get_courts_with_active_case_alerts failed: %s", exc)
        return

    for row in current_snapshot:
        court_no = str(row.get("room_no", "")).strip()
        if not court_no or court_no not in active_courts:
            continue

        current_serial = _current_serial_from_row(row)
        if current_serial is None:
            continue

        try:
            tracked_cases = db.list_active_case_alerts(court_no, today)
        except Exception as exc:
            log.warning("list_active_case_alerts failed court=%s: %s", court_no, exc)
            continue

        for tc in tracked_cases:
            alert_serial = tc.get("alert_serial")
            look_ahead = int(tc.get("look_ahead") or 5)
            if alert_serial is None:
                continue

            threshold = int(alert_serial) - look_ahead
            if current_serial < threshold:
                continue

            try:
                _fire_serial_alert(db, tc, current_serial, today)
            except Exception as exc:
                log.warning(
                    "serial alert fire failed user=%s case=%s: %s",
                    tc.get("user_id"),
                    tc.get("case_ref"),
                    exc,
                )


def _fire_serial_alert(db: Any, tracked_case: dict, current_serial: int, today: str) -> None:
    from .notifications import send_alert

    prefs: dict = {}
    try:
        prefs = db.get_notification_prefs(str(tracked_case["user_id"]))
    except Exception:
        pass
    if not prefs.get("serial_alerts", True):
        return

    send_alert(
        db,
        tracked_case,
        "serial_reached",
        {
            "court_no": tracked_case.get("court_no", ""),
            "current_serial": current_serial,
            "alert_serial": tracked_case.get("alert_serial"),
            "date": today,
        },
    )
    db.update_case_alerted_at(
        str(tracked_case["user_id"]),
        tracked_case["case_ref"],
        today,
    )
    log.info(
        "Serial alert fired: user=%s case=%s court=%s serial=%d",
        tracked_case["user_id"],
        tracked_case["case_ref"],
        tracked_case.get("court_no"),
        current_serial,
    )

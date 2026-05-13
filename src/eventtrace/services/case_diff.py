"""Daily case diff job and causelist-scan alert job."""

from __future__ import annotations

import hashlib
import json
import structlog
from typing import Any

log = structlog.get_logger()

_SNAPSHOT_FIELDS = [
    "serial_no",
    "case_ref",
    "case_type",
    "case_number",
    "case_year",
    "petitioner",
    "respondent",
    "advocate",
    "pro_se",
    "ia_numbers_json",
    "section",
    "subsection",
    "hearing_type",
    "raw_text",
    "court_no",
]


def _serialize_row(row: dict) -> str:
    data = {k: row.get(k) for k in _SNAPSHOT_FIELDS}
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _diff(old_json: str, new_json: str) -> dict:
    try:
        old = json.loads(old_json)
        new = json.loads(new_json)
    except Exception:
        return {}
    changed = []
    all_keys = set(old) | set(new)
    for k in all_keys:
        ov = old.get(k)
        nv = new.get(k)
        if ov != nv:
            changed.append({"field": k, "old": ov, "new": nv})
    return {"changed": changed}


def _get_case_for_date(db: Any, case_ref: str, list_date: str) -> dict | None:
    try:
        results = db.search_causelist_cases(
            case_ref=case_ref, date_from=list_date, date_to=list_date, limit=1
        )
        return results[0] if results else None
    except Exception:
        return None


def run_daily_case_diff(db: Any, date: str) -> None:
    case_refs = db.get_all_tracked_case_refs()
    if not case_refs:
        return
    log.info("run_daily_case_diff: %d case_refs for %s", len(case_refs), date)

    for case_ref in case_refs:
        users = db.get_users_tracking(case_ref)
        if not users:
            continue
        try:
            row = _get_case_for_date(db, case_ref, date)
        except Exception as exc:
            log.warning("case_diff lookup failed for %s: %s", case_ref, exc)
            continue

        if row is None:
            for user_id in users:
                try:
                    db.insert_timeline_event(user_id, case_ref, "NOT_FOUND", date)
                except Exception:
                    pass
            continue

        data_json = _serialize_row(row)
        hash_val = _sha256(data_json)

        last_snap = None
        try:
            last_snap = db.get_last_snapshot(case_ref)
        except Exception:
            pass

        changed = False
        try:
            changed = db.upsert_snapshot(case_ref, date, data_json, hash_val)
        except Exception as exc:
            log.warning("upsert_snapshot failed for %s: %s", case_ref, exc)

        if last_snap is None:
            # First snapshot ever — no comparison possible yet
            for user_id in users:
                try:
                    db.insert_timeline_event(user_id, case_ref, "NO_CHANGE", date)
                except Exception:
                    pass
        elif not changed:
            for user_id in users:
                try:
                    db.insert_timeline_event(user_id, case_ref, "NO_CHANGE", date)
                except Exception:
                    pass
        else:
            diff = _diff(last_snap["data_json"], data_json)
            change_summary = json.dumps(diff) if diff.get("changed") else None
            for user_id in users:
                try:
                    db.insert_timeline_event(user_id, case_ref, "UPDATED", date, change_summary)
                except Exception:
                    pass
            if diff.get("changed"):
                _send_change_alerts(db, case_ref, users, diff, date)


def _send_change_alerts(db: Any, case_ref: str, user_ids: list[str], diff: dict, date: str) -> None:
    from .notifications import send_alert

    summary_parts = [f"{c['field']}: {c['old']} → {c['new']}" for c in diff.get("changed", [])[:3]]
    summary = "; ".join(summary_parts)

    for user_id in user_ids:
        try:
            prefs = db.get_notification_prefs(user_id)
            if not prefs.get("change_alerts", True):
                continue
            tracked = db.get_tracked_case(user_id, case_ref)
            if not tracked:
                continue
            send_alert(
                db,
                tracked,
                "case_updated",
                {
                    "date": date,
                    "summary": summary,
                    "diff": diff,
                },
            )
        except Exception as exc:
            log.warning("change alert failed user=%s case=%s: %s", user_id, case_ref, exc)


def run_causelist_alert_scan(db: Any, date: str) -> None:
    from .notifications import send_alert

    case_refs = db.get_all_tracked_case_refs()
    if not case_refs:
        return
    log.info("run_causelist_alert_scan: %d case_refs for %s", len(case_refs), date)

    for case_ref in case_refs:
        try:
            results = db.search_causelist_cases(
                case_ref=case_ref, date_from=date, date_to=date, limit=5
            )
        except Exception as exc:
            log.warning("causelist scan lookup failed %s: %s", case_ref, exc)
            continue

        if not results:
            continue

        users = db.get_users_tracking(case_ref)
        for row in results:
            court_no = row.get("court_no", "")
            serial_no = row.get("serial_no")

            for user_id in users:
                try:
                    prefs = db.get_notification_prefs(user_id)
                    if not prefs.get("causelist_alerts", True):
                        continue
                    already = db.has_causelist_alert_today(user_id, case_ref, date)
                    if already:
                        continue
                    tracked = db.get_tracked_case(user_id, case_ref)
                    if not tracked:
                        continue
                    send_alert(
                        db,
                        tracked,
                        "case_in_causelist",
                        {
                            "date": date,
                            "court_no": court_no,
                            "serial_no": serial_no,
                            "section": row.get("section", ""),
                            "subsection": row.get("subsection", ""),
                            "bench_label": row.get("bench_label", ""),
                            "vc_link": row.get("vc_link", ""),
                        },
                    )
                    db.insert_timeline_event(user_id, case_ref, "case_in_causelist", date)
                except Exception as exc:
                    log.warning(
                        "causelist alert failed user=%s case=%s: %s", user_id, case_ref, exc
                    )

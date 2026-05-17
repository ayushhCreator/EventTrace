"""Daily case diff job and causelist-scan alert job."""

from __future__ import annotations

import hashlib
import json
import structlog
from typing import Any

_HEARING_FIELDS = frozenset(["next_date", "date_of_hearing", "hearing_date", "listing_date", "next_hearing"])
_JUDGE_FIELDS = frozenset(["presiding_officer", "judge", "bench", "judge_name"])
_ORDER_FIELDS = frozenset(["order", "judgment", "document"])

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


def _classify_change(field: str) -> str:
    fl = field.lower()
    if any(hf in fl for hf in _HEARING_FIELDS):
        return "hearing_date_changed"
    if any(jf in fl for jf in _JUDGE_FIELDS):
        return "judge_changed"
    if any(of in fl for of in _ORDER_FIELDS):
        return "order_uploaded"
    return "status_changed"


def _send_change_alerts(db: Any, case_ref: str, user_ids: list[str], diff: dict, date: str) -> None:
    from .notification_dispatch import enqueue_notification

    changed_fields = diff.get("changed", [])
    # Build one context per distinct trigger type (first match wins per type)
    trigger_contexts: dict[str, dict] = {}
    for c in changed_fields:
        ttype = _classify_change(c["field"])
        if ttype in trigger_contexts:
            continue
        if ttype in ("hearing_date_changed", "judge_changed"):
            trigger_contexts[ttype] = {"old_value": c["old"], "new_value": c["new"], "date": date}
        elif ttype == "order_uploaded":
            trigger_contexts[ttype] = {
                "summary": f"{c['field']}: {c['old']} → {c['new']}",
                "date": date,
            }
        else:
            trigger_contexts[ttype] = {"old_value": c["old"], "new_value": c["new"], "date": date}

    for user_id in user_ids:
        for ttype, ctx in trigger_contexts.items():
            try:
                enqueue_notification(db, user_id, case_ref, ttype, ctx)
            except Exception as exc:
                log.warning("change alert failed user=%s case=%s trigger=%s: %s", user_id, case_ref, ttype, exc)


def _date_label(date_str: str) -> str:
    from datetime import date as _date
    try:
        d = _date.fromisoformat(date_str)
        today = _date.today()
        delta = (d - today).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Tomorrow"
        return date_str
    except Exception:
        return date_str


def _parse_judges(judges_json: Any) -> str:
    import json as _json
    if not judges_json:
        return ""
    try:
        judges = _json.loads(judges_json) if isinstance(judges_json, str) else judges_json
        return ", ".join(j.get("full_name") or j.get("normalized_name") or str(j) for j in judges if j)
    except Exception:
        return str(judges_json)


def run_causelist_alert_scan(db: Any, date: str) -> None:
    from .notification_dispatch import enqueue_notification

    case_refs = db.get_all_tracked_case_refs()
    if not case_refs:
        return
    log.info("run_causelist_alert_scan: %d case_refs for %s", len(case_refs), date)

    date_label = _date_label(date)

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
            case_url = (
                f"https://legal.supersahayak.com/causelist/{date}/court/{court_no}/serial/{serial_no}"
                if court_no and serial_no else
                f"https://legal.supersahayak.com/causelist/{date}"
            )

            for user_id in users:
                try:
                    enqueue_notification(
                        db,
                        user_id,
                        case_ref,
                        "case_in_causelist",
                        {
                            "date": date,
                            "date_label": date_label,
                            "court_no": court_no,
                            "serial_no": serial_no,
                            "section": row.get("section", ""),
                            "subsection": row.get("subsection", ""),
                            "bench_label": row.get("bench_label", ""),
                            "vc_link": row.get("vc_link", ""),
                            "petitioner": row.get("petitioner", ""),
                            "respondent": row.get("respondent", ""),
                            "advocate": row.get("advocate", ""),
                            "judges": _parse_judges(row.get("judges_json")),
                            "case_url": case_url,
                        },
                    )
                    db.insert_timeline_event(user_id, case_ref, "case_in_causelist", date)
                except Exception as exc:
                    log.warning(
                        "causelist alert failed user=%s case=%s: %s", user_id, case_ref, exc
                    )

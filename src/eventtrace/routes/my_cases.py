from __future__ import annotations

import json
import os
import threading
import structlog
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..common.time import ist_today_str
from ..routes.auth import _current_user
from ..services.deps import get_db

log = structlog.get_logger()

router = APIRouter(prefix="/my-cases")


class TrackRequest(BaseModel):
    case_ref: str
    court_no: str | None = None
    bench_label: str | None = None
    judges_json: str | None = None
    list_date: str | None = None
    serial_no: int | None = None
    petitioner: str | None = None
    respondent: str | None = None
    cino: str | None = None
    case_type_id: str | None = None
    state_cd: str | None = None
    court_code: str | None = None
    case_no: str | None = None
    case_year: str | None = None


class AlertRequest(BaseModel):
    alert_serial: int = Field(..., ge=1, le=9999)
    look_ahead: int = Field(5, ge=0, le=50)


@router.get("")
def list_my_cases(
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> list[dict]:
    user_id = str(current_user["id"])
    cases = db.list_tracked_cases(user_id)
    for c in cases:
        try:
            c["causelist_alert"] = db.get_causelist_alert_status(user_id, c["case_ref"])
        except Exception:
            c["causelist_alert"] = False
    return cases


@router.post("", status_code=201)
def track_case(
    req: TrackRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    case_id = db.add_tracked_case(
        current_user["id"],
        req.case_ref,
        court_no=req.court_no,
        bench_label=req.bench_label,
        judges_json=req.judges_json,
        list_date=req.list_date,
        serial_no=req.serial_no,
        petitioner=req.petitioner,
        respondent=req.respondent,
        cino=req.cino,
        case_type_id=req.case_type_id,
        state_cd=req.state_cd,
        court_code=req.court_code,
        case_no=req.case_no,
        case_year=req.case_year,
    )
    today = ist_today_str()
    try:
        db.insert_timeline_event(current_user["id"], req.case_ref, "TRACK_STARTED", today)
    except Exception:
        pass

    # Bulk-import past causelist appearances as timeline events
    try:
        past = db.search_causelist_cases(case_ref=req.case_ref, limit=50)
        for row in past:
            try:
                db.insert_timeline_event(
                    current_user["id"],
                    req.case_ref,
                    "CAUSELIST_APPEARANCE",
                    row["list_date"],
                    json.dumps(
                        {
                            "court_no": row.get("court_no"),
                            "section": row.get("section"),
                            "subsection": row.get("subsection"),
                            "serial_no": row.get("serial_no"),
                            "bench_label": row.get("bench_label"),
                        }
                    ),
                )
            except Exception:
                pass  # skip duplicates silently
    except Exception as exc:
        log.warning("bulk appearance import failed: %s", exc)

    return db.get_tracked_case(current_user["id"], req.case_ref) or {"id": case_id}


@router.post("/{case_ref:path}/alert", status_code=200)
def set_alert(
    case_ref: str,
    req: AlertRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    ok = db.set_case_alert(current_user["id"], case_ref, req.alert_serial, req.look_ahead)
    if not ok:
        raise HTTPException(status_code=404, detail="Case not tracked")
    return db.get_tracked_case(current_user["id"], case_ref)


@router.delete("/{case_ref:path}/alert", status_code=200)
def clear_alert(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    ok = db.clear_case_alert(current_user["id"], case_ref)
    if not ok:
        raise HTTPException(status_code=404, detail="Case not tracked")
    return db.get_tracked_case(current_user["id"], case_ref)


@router.post("/{case_ref:path}/fetch-ecourts", status_code=202)
def fetch_ecourts(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    """Trigger a background eCourts fetch for a tracked case. Returns immediately."""
    case = db.get_tracked_case(current_user["id"], case_ref)
    if not case:
        raise HTTPException(status_code=404, detail="Case not tracked")

    cino = (case.get("cino") or "").strip()
    state_cd = (case.get("state_cd") or "").strip()
    court_code = (case.get("court_code") or "").strip()
    case_type_id = (case.get("case_type_id") or "").strip()
    case_no = (case.get("case_no") or "").strip()
    case_year = str(case.get("case_year") or "").strip()

    # Fallback: derive missing params from case_ref for legacy tracked cases
    # case_ref format: PREFIX/NUMBER/YEAR  e.g. "CO/4068/2025"
    if not case_no or not case_year:
        ref_parts = case_ref.split("/")
        if len(ref_parts) >= 3:
            case_no = case_no or ref_parts[-2]
            case_year = case_year or ref_parts[-1]
    if not state_cd:
        state_cd = "16"  # Calcutta HC
    if not court_code:
        # Derive from bench_label or source_id stored on tracked case
        bench_label = (case.get("bench_label") or "").upper()
        source_id = (case.get("source_id") or "").lower()
        if "original" in bench_label or "original" in source_id:
            court_code = "1"
        else:
            court_code = "3"  # default: appellate

    # Auto-resolve case_type_id from prefix if missing
    if not case_type_id and state_cd and court_code:
        prefix = case_ref.split("/")[0].upper().strip()
        if prefix:
            try:
                from ..services.resolve_ecourts_type import resolve_prefix_to_type_id
                resolved = resolve_prefix_to_type_id(prefix, state_cd, court_code, db)
                if resolved:
                    case_type_id = resolved
                    log.info("fetch-ecourts: resolved %r → type_id %s", prefix, resolved)
                    # Persist so future fetches skip resolution
                    try:
                        db.update_tracked_case(current_user["id"], case_ref, {"case_type_id": resolved})
                    except Exception:
                        pass
            except Exception as exc:
                log.warning("type_id resolution failed for %s: %s", case_ref, exc)

    # cino is optional — _do_case_history discovers it via showRecords when empty
    if not all([state_cd, court_code, case_type_id, case_no, case_year]):
        return {"status": "skipped", "reason": "missing_ecourts_params"}

    # Check if a fresh cache entry already exists (< 6 hours old) when cino is known
    if cino:
        cached = db.get_case_history_cache(cino, state_cd, court_code, max_age_seconds=6 * 3600)
        if cached:
            return {"status": "cached", "cached_at": cached.get("cached_at")}

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"status": "skipped", "reason": "no_api_key"}

    # Capture for closure
    _resolved_type_id = case_type_id
    _cino = cino  # may be empty — discovered in background

    def _bg() -> None:
        try:
            from ..routes.ecourts_test import _do_case_history
            result = _do_case_history(
                state_cd=state_cd,
                court_code=court_code,
                case_type_id=_resolved_type_id,
                case_no=case_no,
                year=case_year,
                target_cino=_cino,
                api_key=api_key,
            )
            # Use discovered cino from result if we didn't have one
            effective_cino = _cino or result.get("cino") or ""
            if not effective_cino:
                log.warning("fetch-ecourts: no cino discovered for %s", case_ref)
                return

            db.set_case_history_cache(
                cino=effective_cino,
                state_cd=state_cd,
                court_code=court_code,
                case_type_id=_resolved_type_id,
                case_no=case_no,
                case_year=case_year,
                data=result,
            )
            log.info("fetch-ecourts: cached %s (cino=%s)", case_ref, effective_cino)

            # Persist discovered cino + type_id back to tracked case
            try:
                updates: dict = {}
                if not _cino and effective_cino:
                    updates["cino"] = effective_cino
                if updates:
                    db.update_tracked_case(current_user["id"], case_ref, updates)
            except Exception:
                pass

            # Auto-learn prefix→type_id mapping
            try:
                from ..services.resolve_ecourts_type import record_learned_prefix
                prefix = case_ref.split("/")[0].upper().strip()
                if prefix and _resolved_type_id:
                    record_learned_prefix(state_cd, court_code, _resolved_type_id, prefix, db)
            except Exception:
                pass
        except Exception as exc:
            log.warning("fetch-ecourts failed for %s: %s", case_ref, exc)

    threading.Thread(target=_bg, daemon=True, name=f"ecourts-fetch-{case_ref}").start()
    return {"status": "fetching"}


@router.post("/notify", status_code=200)
def subscribe_causelist_alert(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    """Subscribe to case_in_causelist notifications. case_ref passed as query param to avoid path-encoding issues."""
    user_id = str(current_user["id"])

    existing = db.get_tracked_case(user_id, case_ref)
    if not existing:
        db.add_tracked_case(user_id, case_ref)

    db.upsert_single_alert_pref(user_id, case_ref, "case_in_causelist", enabled=True)

    user = db.get_user_by_id(user_id) or {}
    channels = []
    if user.get("telegram_chat_id"):
        channels.append("telegram")
    if user.get("email_verified") and user.get("email") and user.get("email_valid", True):
        channels.append("email")
    if not channels:
        channels = ["pending_setup"]

    return {"subscribed": True, "case_ref": case_ref, "channels": channels}


@router.delete("/notify", status_code=200)
def unsubscribe_causelist_alert(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    """Unsubscribe from case_in_causelist notifications. case_ref passed as query param."""
    user_id = str(current_user["id"])
    db.upsert_single_alert_pref(user_id, case_ref, "case_in_causelist", enabled=False)
    return {"subscribed": False, "case_ref": case_ref}


@router.delete("/{case_ref:path}", status_code=204)
def untrack_case(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> None:
    removed = db.remove_tracked_case(current_user["id"], case_ref)
    if not removed:
        raise HTTPException(status_code=404, detail="Case not tracked")


# ── Notification prefs ───────────────────────────────────────────────────────

_ALL_TRIGGER_TYPES = [
    "case_in_causelist",
    "serial_reached",
    "display_board_active",
    "hearing_date_changed",
    "order_uploaded",
    "status_changed",
    "judge_changed",
]

_DEFAULT_PREF = {"channel": "whatsapp", "enabled": True, "quiet_hours_start": None, "quiet_hours_end": None}


class AlertPrefItem(BaseModel):
    trigger_type: str
    channel: str = "whatsapp"
    enabled: bool = True
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None


class AlertPrefPatch(BaseModel):
    channel: str | None = None
    enabled: bool | None = None
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None


@router.get("/{case_ref:path}/notification-prefs")
def get_notification_prefs(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> list[dict]:
    existing = {p["trigger_type"]: p for p in db.get_alert_prefs(current_user["id"], case_ref)}
    result = []
    for t in _ALL_TRIGGER_TYPES:
        if t in existing:
            result.append(existing[t])
        else:
            result.append({"trigger_type": t, "user_id": current_user["id"], "case_ref": case_ref, **_DEFAULT_PREF})
    return result


@router.put("/{case_ref:path}/notification-prefs")
def set_notification_prefs(
    case_ref: str,
    prefs: list[AlertPrefItem],
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> list[dict]:
    valid = {p.trigger_type for p in prefs if p.trigger_type in _ALL_TRIGGER_TYPES}
    if not valid:
        raise HTTPException(status_code=422, detail="No valid trigger_types provided")
    return db.upsert_alert_prefs(
        current_user["id"],
        case_ref,
        [p.model_dump() for p in prefs if p.trigger_type in _ALL_TRIGGER_TYPES],
    )


@router.patch("/{case_ref:path}/notification-prefs/{trigger_type}")
def patch_notification_pref(
    case_ref: str,
    trigger_type: str,
    body: AlertPrefPatch,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    if trigger_type not in _ALL_TRIGGER_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown trigger_type: {trigger_type}")
    return db.upsert_single_alert_pref(
        current_user["id"],
        case_ref,
        trigger_type,
        channel=body.channel,
        enabled=body.enabled,
        quiet_hours_start=body.quiet_hours_start,
        quiet_hours_end=body.quiet_hours_end,
    )


# ── Timeline endpoint (Task 5) ────────────────────────────────────────────────

timeline_router = APIRouter()


@timeline_router.get("/case/{case_ref:path}/timeline")
def get_case_timeline(
    case_ref: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    tracked = db.get_tracked_case(current_user["id"], case_ref)
    if not tracked:
        raise HTTPException(status_code=404, detail="Case not tracked")

    events_raw = db.get_timeline(current_user["id"], case_ref, limit)

    # Parse change_summary JSON strings
    events: list[dict] = []
    for e in events_raw:
        row = dict(e)
        if row.get("change_summary") and isinstance(row["change_summary"], str):
            try:
                row["change_summary"] = json.loads(row["change_summary"])
            except Exception:
                pass
        events.append(row)

    # De-duplicate events that are identical in meaning (same type/date/summary).
    # Some flows can insert duplicates (e.g. repeated "TRACK_STARTED" on retries).
    deduped: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        try:
            summary_key = json.dumps(ev.get("change_summary"), sort_keys=True, ensure_ascii=False)
        except Exception:
            summary_key = str(ev.get("change_summary"))
        key = f"{ev.get('event_type','')}|{ev.get('event_date','')}|{summary_key}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)
    events = deduped

    # Compute stats
    appeared = sum(1 for e in events if e["event_type"] in ("NO_CHANGE", "UPDATED"))
    changes = sum(1 for e in events if e["event_type"] == "UPDATED")
    tracking_since = tracked.get("added_at", "")

    from ..common.time import ist_today_str

    today = ist_today_str()

    if tracking_since:
        try:
            from datetime import date

            start = date.fromisoformat(tracking_since[:10])
            days_tracked = (date.fromisoformat(today) - start).days + 1
        except Exception:
            days_tracked = len(events)
    else:
        days_tracked = len(events)

    return {
        "case_ref": case_ref,
        "tracking_since": tracking_since,
        "stats": {
            "days_tracked": days_tracked,
            "times_appeared": appeared,
            "changes_detected": changes,
        },
        "events": events,
    }

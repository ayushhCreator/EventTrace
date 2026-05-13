from __future__ import annotations

import json
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
    return db.list_tracked_cases(current_user["id"])


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


@router.delete("/{case_ref:path}", status_code=204)
def untrack_case(
    case_ref: str,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> None:
    removed = db.remove_tracked_case(current_user["id"], case_ref)
    if not removed:
        raise HTTPException(status_code=404, detail="Case not tracked")


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

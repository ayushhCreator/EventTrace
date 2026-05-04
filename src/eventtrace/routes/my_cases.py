from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..routes.auth import _current_user
from ..services.deps import get_db

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
    )
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

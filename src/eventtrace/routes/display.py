from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..services.deps import get_db
from .utils import today_ist

router = APIRouter()


@router.get("/current-state")
def current_state(db: Any = Depends(get_db)) -> list[dict]:
    return db.list_current_state()


@router.get("/vc-links")
def vc_links(
    date: str | None = Query(None, description="YYYY-MM-DD IST, defaults to today"),
    db: Any = Depends(get_db),
) -> dict[str, str]:
    return db.get_vc_zoom_links(date or today_ist())


@router.get("/vc-links/dates")
def vc_link_dates(db: Any = Depends(get_db)) -> list[str]:
    return db.list_vc_dates()


@router.get("/changes")
@router.get("/event-traces")
def event_traces(
    limit: int = Query(200, ge=1, le=2000),
    court_id: str | None = None,
    db: Any = Depends(get_db),
) -> list[dict]:
    return db.list_event_traces(limit=limit, court_id=court_id)


@router.get("/field-state/{court_id}")
def field_state(court_id: str, db: Any = Depends(get_db)) -> list[dict]:
    return db.list_field_state(court_id)


@router.get("/absent-courts")
def absent_courts(db: Any = Depends(get_db)) -> list[str]:
    return db.list_absent_court_ids()


@router.get("/field-durations")
def field_durations(db: Any = Depends(get_db)) -> dict[str, str]:
    return db.list_serial_start_times()

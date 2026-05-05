from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..services.csv_export import csv_response
from ..services.deps import get_db

router = APIRouter()


@router.get("/export/current-state.csv")
def export_current_state_csv(db: Any = Depends(get_db)):
    rows = db.list_current_state()
    if not rows:
        return csv_response(
            rows=[], fieldnames=["court_id", "last_seen_time"], filename="current_state.csv"
        )

    all_keys: list[str] = []
    for r in rows:
        for k in r["data"].keys():
            if k not in all_keys:
                all_keys.append(k)

    fieldnames = ["court_id", "last_seen_time"] + all_keys
    flat_rows: list[dict] = []
    for r in rows:
        flat = {"court_id": r["court_id"], "last_seen_time": r["last_seen_time"]}
        flat.update(r["data"])
        flat_rows.append(flat)
    return csv_response(rows=flat_rows, fieldnames=fieldnames, filename="current_state.csv")


@router.get("/export/event-traces.csv")
def export_event_traces_csv(
    limit: int = Query(2000, ge=1, le=100000),
    court_id: str | None = None,
    db: Any = Depends(get_db),
):
    rows = db.list_event_traces(limit=limit, court_id=court_id)
    fieldnames = [
        "id",
        "court_id",
        "field_name",
        "old_value",
        "new_value",
        "start_time",
        "end_time",
        "duration_seconds",
        "observed_time",
    ]
    return csv_response(rows=rows, fieldnames=fieldnames, filename="event_traces.csv")

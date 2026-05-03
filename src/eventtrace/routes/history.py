from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..services.deps import get_db

router = APIRouter()


@router.get("/history/dates")
def history_dates(db: Any = Depends(get_db)) -> list[str]:
    return db.list_active_dates()


@router.get("/history/day")
def history_day(date: str = Query(..., description="YYYY-MM-DD in IST"), db: Any = Depends(get_db)) -> list[dict]:
    return db.list_day_activity(date)


from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..routes.auth import _current_user
from ..services.deps import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(current_user: dict = Depends(_current_user)) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user


@router.get("/stats/notifications")
def notification_stats(
    days: int = Query(7, ge=1, le=90),
    db: Any = Depends(get_db),
    _: dict = Depends(_require_admin),
) -> dict:
    return db.get_notification_stats(days)


@router.get("/stats/users")
def user_stats(
    db: Any = Depends(get_db),
    _: dict = Depends(_require_admin),
) -> dict:
    return db.get_user_stats()


@router.get("/stats/searches")
def search_stats(
    limit: int = Query(20, ge=1, le=100),
    db: Any = Depends(get_db),
    _: dict = Depends(_require_admin),
) -> list[dict]:
    return db.get_top_searches(limit)


@router.get("/users")
def list_users(
    db: Any = Depends(get_db),
    _: dict = Depends(_require_admin),
) -> list[dict]:
    return db.list_all_users_with_stats()


@router.get("/system")
def system_health(
    db: Any = Depends(get_db),
    _: dict = Depends(_require_admin),
) -> dict:
    last_poll = db.get_monitor_state("last_successful_poll")
    board_active = db.get_monitor_state("board_active")

    try:
        current_state = db.list_current_state()
        active_courts = len(current_state)
    except Exception:
        active_courts = 0

    try:
        causelist_dates = db.list_causelist_dates()
    except Exception:
        causelist_dates = []

    try:
        notification_stats = db.get_notification_stats(7)
    except Exception:
        notification_stats = {}

    return {
        "monitor": {
            "last_successful_poll": last_poll,
            "board_active": board_active == "1",
            "active_courts": active_courts,
        },
        "causelist": {
            "scraped_dates": causelist_dates[:10],
            "latest_date": causelist_dates[0] if causelist_dates else None,
        },
        "notifications_7d": notification_stats,
    }

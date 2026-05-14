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

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..routes.auth import _current_user
from ..services.deps import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    case_ref: str | None = Query(None),
    db: Any = Depends(get_db),
    current_user: dict = Depends(_current_user),
) -> dict:
    user_id = str(current_user["id"])
    items, total = db.get_user_notifications(
        user_id, limit=limit, offset=offset, case_ref=case_ref, unread_only=unread_only
    )
    unread = db.count_unread_notifications(user_id)
    return {
        "notifications": items,
        "total": total,
        "unread_count": unread,
        "limit": limit,
        "offset": offset,
    }


@router.get("/unread-count")
def unread_count(
    db: Any = Depends(get_db),
    current_user: dict = Depends(_current_user),
) -> dict:
    return {"unread_count": db.count_unread_notifications(str(current_user["id"]))}


@router.post("/{notification_id}/mark-read")
def mark_read(
    notification_id: int,
    db: Any = Depends(get_db),
    current_user: dict = Depends(_current_user),
) -> dict:
    ok = db.mark_notification_read(notification_id, str(current_user["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/mark-all-read")
def mark_all_read(
    db: Any = Depends(get_db),
    current_user: dict = Depends(_current_user),
) -> dict:
    count = db.mark_all_notifications_read(str(current_user["id"]))
    return {"marked": count}

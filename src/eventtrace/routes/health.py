from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..core.redis_client import get_redis

log = structlog.get_logger()
router = APIRouter()


@router.get("/health")
def health(request: Request) -> JSONResponse:
    """Returns {status, db, redis, timestamp} — 200 ok or 503 degraded."""
    db_ok = _check_db(request)
    redis_ok = _check_redis()
    timestamp = datetime.now(timezone.utc).isoformat()

    all_ok = db_ok and redis_ok
    payload = {
        "status": "ok" if all_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else ("disabled" if get_redis() is None and not _redis_url_set() else "error"),
        "timestamp": timestamp,
    }
    status_code = 200 if all_ok else 503
    return JSONResponse(content=payload, status_code=status_code)


def _check_db(request: Request) -> bool:
    try:
        db = getattr(request.app.state, "db", None)
        if db is None:
            return False
        db.list_current_state()
        return True
    except Exception as exc:
        log.warning("health.db_check_failed", error=str(exc))
        return False


def _check_redis() -> bool:
    try:
        r = get_redis()
        if r is None:
            return True  # Redis optional — not configured is not a failure
        r.ping()
        return True
    except Exception as exc:
        log.warning("health.redis_check_failed", error=str(exc))
        return False


def _redis_url_set() -> bool:
    import os
    return bool(os.getenv("REDIS_URL", ""))

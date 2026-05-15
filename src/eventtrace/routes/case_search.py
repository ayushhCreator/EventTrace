"""Unified case search: causelist DB + cached eCourts data (no live CAPTCHA)."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.deps import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api")


@router.post("/case-search")
async def unified_case_search(request: Request) -> dict:
    db: Any = get_db(request)
    body = await request.json()
    raw_ref = (body.get("case_ref") or "").strip()

    if not raw_ref:
        return JSONResponse({"error": "case_ref is required"}, status_code=400)

    # 1. Internal causelist search — instant, no CAPTCHA
    appearances: list[dict] = []
    try:
        appearances = db.search_causelist_cases(case_ref=raw_ref, limit=20)
    except Exception as exc:
        log.warning("causelist search failed: %s", exc)

    # 2. Is the requesting user already tracking this case?
    is_tracked = False
    tracked_case: dict | None = None
    user_id: str | None = None
    try:
        from ..services import auth as auth_svc

        token = request.cookies.get("et_token")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
        if token:
            settings = request.app.state.settings
            payload = auth_svc.decode_jwt(token, settings)
            user_id = payload.get("sub")
            if user_id:
                tracked_case = db.get_tracked_case(user_id, raw_ref)
                is_tracked = bool(tracked_case)
    except Exception:
        pass

    # 3. Return cached eCourts data if available (populated by fetch-ecourts or daily refresh)
    ecourts_data: dict | None = None
    if tracked_case:
        cino = (tracked_case.get("cino") or "").strip()
        state_cd = (tracked_case.get("state_cd") or "").strip()
        court_code = (tracked_case.get("court_code") or "").strip()
        if cino and state_cd and court_code:
            try:
                ecourts_data = db.get_case_history_cache(cino, state_cd, court_code)
            except Exception as exc:
                log.warning("case_history_cache lookup failed: %s", exc)

    return {
        "case_ref": raw_ref,
        "ecourts": ecourts_data,
        "causelist_appearances": appearances,
        "is_tracked": is_tracked,
    }

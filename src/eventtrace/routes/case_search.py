"""Unified case search: merges eCourts lookup + internal causelist DB."""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.deps import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api")

_CASE_REF_RE = re.compile(r"^([A-Za-z][A-Za-z0-9.()\-]*)[\s/]+(\d+)(?:[\s/]+(\d{4}))?$")


@router.post("/case-search")
async def unified_case_search(request: Request) -> dict:
    db: Any = get_db(request)
    body = await request.json()
    raw_ref = (body.get("case_ref") or "").strip()
    include_ecourts = body.get("include_ecourts", True)
    # Optional eCourts params — required if include_ecourts=True
    case_type_id = str(body.get("case_type_id") or "").strip()
    state_cd = str(body.get("state_cd") or "16").strip()
    court_code = str(body.get("court_code") or "3").strip()

    if not raw_ref:
        return JSONResponse({"error": "case_ref is required"}, status_code=400)

    # 1. Internal causelist search (fast, no CAPTCHA)
    appearances: list[dict] = []
    try:
        appearances = db.search_causelist_cases(case_ref=raw_ref, limit=20)
    except Exception as exc:
        log.warning("causelist search failed: %s", exc)

    # 2. eCourts lookup (optional — requires case_type_id + anthropic_api_key)
    ecourts_data: dict | None = None
    if include_ecourts and case_type_id:
        settings = request.app.state.settings
        import os

        api_key = getattr(settings, "anthropic_api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            m = _CASE_REF_RE.match(raw_ref)
            if m:
                case_no = m.group(2)
                year = m.group(3) or ""
                try:
                    from ..routes.ecourts_test import _do_case_search

                    results = _do_case_search(
                        state_cd=state_cd,
                        court_code=court_code,
                        case_type_id=case_type_id,
                        case_no=case_no,
                        year=year,
                        api_key=api_key,
                    )
                    ecourts_data = {"results": results, "count": len(results)}
                except Exception as exc:
                    ecourts_data = {"error": str(exc)}
        elif include_ecourts and not api_key:
            ecourts_data = {"error": "ANTHROPIC_API_KEY not configured"}

    # 3. Is the requesting user already tracking this case?
    is_tracked = False
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
                is_tracked = bool(db.get_tracked_case(user_id, raw_ref))
    except Exception:
        pass

    return {
        "case_ref": raw_ref,
        "ecourts": ecourts_data,
        "causelist_appearances": appearances,
        "is_tracked": is_tracked,
    }

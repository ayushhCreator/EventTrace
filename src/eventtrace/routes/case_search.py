"""Unified case search: causelist DB + cached eCourts data (no live CAPTCHA)."""

from __future__ import annotations

import os
import threading
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..services.deps import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api")


def _background_ecourts_fetch(
    db: Any,
    user_id: str,
    case_ref: str,
    prefix: str,
    case_no: str,
    case_year: str,
    state_cd: str,
    court_code: str,
    api_key: str,
) -> None:
    try:
        from ..services.resolve_ecourts_type import resolve_prefix_to_type_id

        type_id = resolve_prefix_to_type_id(prefix, state_cd, court_code, db)
        if not type_id:
            log.warning("auto-ecourts: could not resolve type_id for prefix=%s", prefix)
            return

        from ..routes.ecourts_test import _do_case_history

        result = _do_case_history(state_cd, court_code, type_id, case_no, case_year, "", api_key)
        cino: str = result.get("cino") or ""
        if not cino:
            log.warning("auto-ecourts: no cino discovered for %s", case_ref)
            return

        db.set_case_history_cache(cino, state_cd, court_code, type_id, case_no, case_year, result)
        db.update_tracked_case(user_id, case_ref, {"cino": cino, "case_type_id": type_id})
        log.info("auto-ecourts: cached %s (cino=%s)", case_ref, cino)
    except Exception as exc:
        log.warning("auto-ecourts failed for %s: %s", case_ref, exc)


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

    # 2. Resolve user identity
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

    # 3. Auto-track: if user logged in and case not yet tracked
    auto_tracked = False
    if user_id and not is_tracked:
        parts = raw_ref.split("/")
        if len(parts) >= 3:
            prefix = parts[0].upper().strip()
            case_no_str = parts[-2].strip()
            case_year_str = parts[-1].strip()

            # Infer court from causelist appearances (Original vs Appellate)
            state_cd_auto = "16"  # Calcutta HC default
            court_code_auto = "3"  # Appellate default
            if appearances:
                bench = (appearances[0].get("bench_label") or "").upper()
                if "ORIGINAL" in bench:
                    court_code_auto = "1"

            try:
                db.add_tracked_case(
                    user_id,
                    raw_ref,
                    case_no=case_no_str,
                    case_year=int(case_year_str) if case_year_str.isdigit() else None,
                    state_cd=state_cd_auto,
                    court_code=court_code_auto,
                )
                auto_tracked = True
                is_tracked = True
                tracked_case = db.get_tracked_case(user_id, raw_ref)

                # Subscribe to causelist notifications automatically
                try:
                    db.upsert_single_alert_pref(user_id, raw_ref, "case_in_causelist", enabled=True)
                except Exception as exc:
                    log.warning("auto-subscribe causelist alert failed: %s", exc)

                # Fire background eCourts fetch (CAPTCHA solve, non-blocking)
                api_key = os.getenv("ANTHROPIC_API_KEY", "")
                if api_key and prefix and case_no_str and case_year_str:
                    threading.Thread(
                        target=_background_ecourts_fetch,
                        args=(db, user_id, raw_ref, prefix, case_no_str, case_year_str, state_cd_auto, court_code_auto, api_key),
                        daemon=True,
                        name=f"auto-ecourts-{raw_ref}",
                    ).start()

            except Exception as exc:
                log.warning("auto-track failed for %s: %s", raw_ref, exc)

    # 4. Return cached eCourts data if available
    # Shape: {results: [{cnr, case_ref}], count} — frontend reads results[0].cnr
    # to fire getCaseHistory which hits /ecourts-test/api/case-history from cache.
    ecourts_payload: dict | None = None
    if tracked_case:
        cino = (tracked_case.get("cino") or "").strip()
        state_cd = (tracked_case.get("state_cd") or "").strip()
        court_code = (tracked_case.get("court_code") or "").strip()
        if cino and state_cd and court_code:
            try:
                history = db.get_case_history_cache(cino, state_cd, court_code)
                if history:
                    ecourts_payload = {
                        "results": [{"cnr": cino, "case_ref": raw_ref}],
                        "count": 1,
                    }
            except Exception as exc:
                log.warning("case_history_cache lookup failed: %s", exc)

    return {
        "case_ref": raw_ref,
        "ecourts": ecourts_payload,
        "causelist_appearances": appearances,
        "is_tracked": is_tracked,
        "auto_tracked": auto_tracked,
    }

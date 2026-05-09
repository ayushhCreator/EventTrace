from __future__ import annotations

import structlog
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..routes.auth import _current_user
from ..services.deps import get_db, get_settings

log = structlog.get_logger()
router = APIRouter(prefix="/matters", tags=["matters"])


class MatterCreate(BaseModel):
    case_ref: str
    case_title: str | None = None
    case_type: str | None = None
    case_number: str | None = None
    case_year: int | None = None
    court_no: str | None = None
    petitioner: str | None = None
    respondent: str | None = None
    billing_mode: str = Field("appearance", pattern="^(appearance|retainer|fixed)$")
    fee_per_appearance: float | None = Field(None, ge=0)
    notes: str | None = None
    opened_at: str | None = None


class MatterUpdate(BaseModel):
    case_title: str | None = None
    court_no: str | None = None
    petitioner: str | None = None
    respondent: str | None = None
    billing_mode: str | None = Field(None, pattern="^(appearance|retainer|fixed)$")
    fee_per_appearance: float | None = Field(None, ge=0)
    notes: str | None = None
    status: str | None = Field(None, pattern="^(active|disposed|stayed|closed)$")
    opened_at: str | None = None
    closed_at: str | None = None


@router.get("/ecourts-lookup")
def ecourts_lookup(
    case_ref: str = Query(..., description="e.g. WPA/4068/2025"),
    current_user: dict = Depends(_current_user),
    settings: Any = Depends(get_settings),
) -> dict:
    """Fetch case details from eCourts Calcutta HC using Claude Vision CAPTCHA solving."""
    from ..services.ecourts import lookup_case

    api_key = getattr(settings, "anthropic_api_key", None)
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured — eCourts lookup unavailable",
        )
    try:
        result = lookup_case(case_ref, api_key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        log.warning("eCourts lookup failed for %s: %s", case_ref, e)
        raise HTTPException(status_code=502, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found on eCourts")
    return result


@router.get("")
def list_matters(
    status: str | None = Query(None),
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> list[dict]:
    return db.list_matters(current_user["id"], status=status)


@router.post("", status_code=201)
def create_matter(
    req: MatterCreate,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    case_ref = req.case_ref.strip().upper()
    if not case_ref:
        raise HTTPException(status_code=422, detail="case_ref required")
    return db.create_matter(
        user_id=current_user["id"],
        case_ref=case_ref,
        case_title=req.case_title,
        case_type=req.case_type,
        case_number=req.case_number,
        case_year=req.case_year,
        court_no=req.court_no,
        petitioner=req.petitioner,
        respondent=req.respondent,
        billing_mode=req.billing_mode,
        fee_per_appearance=req.fee_per_appearance,
        notes=req.notes,
        opened_at=req.opened_at,
    )


@router.get("/{matter_id}")
def get_matter(
    matter_id: int,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    m = db.get_matter(current_user["id"], matter_id)
    if not m:
        raise HTTPException(status_code=404, detail="Matter not found")
    return m


@router.patch("/{matter_id}")
def update_matter(
    matter_id: int,
    req: MatterUpdate,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    m = db.update_matter(
        current_user["id"],
        matter_id,
        **{k: v for k, v in req.model_dump().items() if v is not None},
    )
    if not m:
        raise HTTPException(status_code=404, detail="Matter not found")
    return m


@router.delete("/{matter_id}", status_code=204)
def delete_matter(
    matter_id: int,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> None:
    ok = db.delete_matter(current_user["id"], matter_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Matter not found")

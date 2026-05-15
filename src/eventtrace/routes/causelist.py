from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials
from ..services.deps import get_db, get_settings
from ..services import auth as _auth_svc

_opt_bearer = _HTTPBearer(auto_error=False)
_COOKIE_NAME = "et_token"


def _optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_opt_bearer),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict | None:
    token = request.cookies.get(_COOKIE_NAME)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        return None
    try:
        payload = _auth_svc.decode_jwt(token, settings)
        return db.get_user_by_id(payload["sub"])
    except Exception:
        return None

router = APIRouter(prefix="/causelist")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# NOTE: static paths (/dates, /search) MUST come before /{list_date}.
@router.get("/dates")
def causelist_dates(db: Any = Depends(get_db)) -> list[str]:
    return db.list_causelist_dates()


@router.get("/prefixes")
def causelist_prefixes(db: Any = Depends(get_db)) -> list[str]:
    """Distinct case-ref prefixes (MAT, FMA, CPAN …) from stored causelist data."""
    return db.list_causelist_prefixes()


@router.get("/search")
def causelist_search(
    case_ref: str | None = Query(None),
    advocate: str | None = Query(None),
    party: str | None = Query(None),
    judge: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    side: str | None = Query(None),
    list_type: str | None = Query(None),
    section: str | None = Query(None, description="Filter by section/category e.g. PIL, GROUP_IX, CONTEMPT"),
    limit: int = Query(100, ge=1, le=500),
    db: Any = Depends(get_db),
    current_user: dict | None = Depends(_optional_user),
) -> list[dict]:
    if not any([case_ref, advocate, party, judge, section]):
        raise HTTPException(
            status_code=422, detail="Provide at least one of: case_ref, advocate, party, judge, section"
        )
    results = db.search_causelist_cases(
        case_ref=case_ref,
        advocate=advocate,
        party=party,
        judge=judge,
        date_from=date_from,
        date_to=date_to,
        side=side,
        list_type=list_type,
        section=section,
        limit=limit,
    )
    if current_user:
        query_parts = [f"{k}={v}" for k, v in [
            ("case_ref", case_ref), ("advocate", advocate), ("party", party),
            ("judge", judge), ("section", section),
        ] if v]
        try:
            db.log_search(
                user_id=str(current_user["id"]),
                query_type="causelist",
                query_text="; ".join(query_parts),
                result_count=len(results),
            )
        except Exception:
            pass
    return results


@router.get("/{list_date}/available-types")
def causelist_available_types(
    list_date: str,
    db: Any = Depends(get_db),
) -> list[dict]:
    """Which (side, list_type) combos have data for a date. Used for supplementary badges."""
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    return db.list_available_list_types(list_date)


@router.get("/{list_date}/judges")
def causelist_judges(
    list_date: str,
    side: str | None = Query(None),
    db: Any = Depends(get_db),
) -> list[dict]:
    """Distinct judges sitting on a date (from canonical judge table)."""
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    return db.list_judges_for_date(list_date, side=side)


@router.get("/{list_date}/bench/{bench_id}/rules")
def causelist_bench_rules(
    list_date: str,
    bench_id: int,
    db: Any = Depends(get_db),
) -> list[dict]:
    """Operational rules (day_order, notes, times) for one bench."""
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    return db.list_bench_rules(bench_id)


@router.get("/{list_date}")
def causelist_summary(
    list_date: str,
    side: str | None = Query(None),
    list_type: str | None = Query(None),
    source_id: str | None = Query(None),
    db: Any = Depends(get_db),
) -> list[dict]:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    return db.list_causelist_benches(list_date, side=side, list_type=list_type, source_id=source_id)


@router.get("/{list_date}/bench/{bench_id}")
def causelist_bench_by_id(
    list_date: str,
    bench_id: int,
    db: Any = Depends(get_db),
) -> dict:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    bench = db.get_bench_by_id(bench_id)
    if not bench:
        raise HTTPException(status_code=404, detail="Bench not found")
    cases = db.list_cases_by_bench_id(bench_id)
    return {"bench": bench, "cases": cases}


@router.get("/{list_date}/court/{court_no}")
def causelist_court(
    list_date: str,
    court_no: str,
    side: str | None = Query(None),
    list_type: str | None = Query(None),
    source_id: str | None = Query(None),
    db: Any = Depends(get_db),
) -> dict:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    bench = db.get_causelist_bench(
        list_date, court_no, side=side, list_type=list_type, source_id=source_id
    )
    if not bench:
        raise HTTPException(status_code=404, detail="Court not found for that date")
    cases = db.list_causelist_cases(
        list_date, court_no, side=side, list_type=list_type, source_id=source_id
    )
    return {"bench": bench, "cases": cases}


@router.get("/{list_date}/court/{court_no}/serial/{serial_no}")
def causelist_serial(
    list_date: str, court_no: str, serial_no: int, db: Any = Depends(get_db)
) -> dict:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    row = db.get_causelist_case_by_serial(list_date, court_no, serial_no)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row

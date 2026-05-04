from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..services.deps import get_db

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
    limit: int = Query(100, ge=1, le=500),
    db: Any = Depends(get_db),
) -> list[dict]:
    if not any([case_ref, advocate, party, judge]):
        raise HTTPException(status_code=422, detail="Provide at least one of: case_ref, advocate, party, judge")
    return db.search_causelist_cases(
        case_ref=case_ref,
        advocate=advocate,
        party=party,
        judge=judge,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.get("/{list_date}")
def causelist_summary(list_date: str, db: Any = Depends(get_db)) -> list[dict]:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    return db.list_causelist_benches(list_date)


@router.get("/{list_date}/court/{court_no}")
def causelist_court(list_date: str, court_no: str, db: Any = Depends(get_db)) -> dict:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    bench = db.get_causelist_bench(list_date, court_no)
    if not bench:
        raise HTTPException(status_code=404, detail="Court not found for that date")
    cases = db.list_causelist_cases(list_date, court_no)
    return {"bench": bench, "cases": cases}


@router.get("/{list_date}/court/{court_no}/serial/{serial_no}")
def causelist_serial(list_date: str, court_no: str, serial_no: int, db: Any = Depends(get_db)) -> dict:
    if not _DATE_RE.match(list_date):
        raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
    row = db.get_causelist_case_by_serial(list_date, court_no, serial_no)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return row


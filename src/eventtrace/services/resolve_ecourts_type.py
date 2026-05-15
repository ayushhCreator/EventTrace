"""Resolve causelist prefix (e.g. "CPAN") → eCourts numeric type_id.

Strategy:
  1. Check cache table ecourts_case_type_map for a stored prefix→type_id mapping.
  2. If table is empty for this bench, call fillCaseType (no CAPTCHA) to populate it.
  3. After populating, try exact match on prefix, then heuristic name match.
  4. `record_learned_prefix` persists a confirmed mapping after a successful search.

Name-matching heuristic (step 3):
  - Exact prefix == id  (eCourts sometimes uses id as prefix)
  - Prefix matches start of type_name  e.g. "CPAN" matches "CPAN - COMPANY APPEAL"
  - type_name starts with prefix  (same in reverse)
"""

from __future__ import annotations

import re
from typing import Any

import requests
import structlog

log = structlog.get_logger()

_BASE = "https://hcservices.ecourts.gov.in/ecourtindiaHC"
_QRY_URL = f"{_BASE}/cases/case_no_qry.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Referer": "https://hcservices.ecourts.gov.in/hcservices/main.php",
    "X-Requested-With": "XMLHttpRequest",
}


def _page_url(state_cd: str, court_code: str) -> str:
    return (
        f"{_BASE}/cases/case_no.php"
        f"?state_cd={state_cd}&dist_cd=1&court_code={court_code}"
    )


def fetch_bench_types(state_cd: str, court_code: str) -> list[dict]:
    """Call fillCaseType (no CAPTCHA). Returns list of {id, name} dicts."""
    page_url = _page_url(state_cd, court_code)
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Referer": page_url})
    try:
        sess.get(page_url, timeout=15)
        r = sess.post(
            _QRY_URL,
            data={
                "action_code": "fillCaseType",
                "state_code": state_cd,
                "dist_code": "1",
                "court_code": court_code,
            },
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:
        log.error("fillCaseType failed for %s/%s: %s", state_cd, court_code, exc)
        return []

    raw = r.text.strip().lstrip("﻿")
    types = []
    for chunk in raw.split("#"):
        chunk = chunk.strip()
        if "~" not in chunk:
            continue
        id_part, _, name_part = chunk.partition("~")
        id_val = id_part.strip()
        name_val = name_part.strip()
        if id_val and id_val != "0":
            types.append({"id": id_val, "name": name_val})
    return types


def populate_bench_types(state_cd: str, court_code: str, db: Any) -> int:
    """Fetch all case types from eCourts and store in cache. Returns count stored."""
    types = fetch_bench_types(state_cd, court_code)
    if not types:
        return 0
    for t in types:
        db.upsert_ecourts_type(state_cd, court_code, t["id"], t["name"])
    log.info(
        "Populated %d case types for bench %s/%s", len(types), state_cd, court_code
    )
    return len(types)


def _match_prefix_in_types(prefix: str, types: list[dict]) -> str | None:
    """Return type_id whose name best matches prefix. None if no match."""
    p = prefix.upper().strip()
    for t in types:
        name_upper = (t.get("type_name") or t.get("name", "")).upper()
        tid = t.get("type_id") or t.get("id", "")
        # Exact match on ID string (some benches use ID==abbrev)
        if tid.upper() == p:
            return tid
        # Name starts with prefix (e.g. "CPAN - COMPANY APPEAL" starts with "CPAN")
        if name_upper.startswith(p):
            return tid
        # Prefix matches first token of name
        first_token = re.split(r"[\s\-/]", name_upper)[0]
        if first_token == p:
            return tid
    return None


def resolve_prefix_to_type_id(
    prefix: str, state_cd: str, court_code: str, db: Any
) -> str | None:
    """
    Resolve a causelist prefix to an eCourts numeric type_id.

    1. DB cache lookup (fast path).
    2. If cache miss but table unpopulated → call fillCaseType, then retry.
    3. Apply name-matching heuristic against all types for this bench.
    4. Persist any newly learned mapping.
    Returns None if unresolvable.
    """
    # Fast path: already in cache
    cached = db.get_ecourts_type_id(state_cd, court_code, prefix)
    if cached:
        return cached

    # Populate if bench not yet cached
    if not db.ecourts_types_populated(state_cd, court_code):
        log.info("Types cache empty for %s/%s — fetching from eCourts", state_cd, court_code)
        populate_bench_types(state_cd, court_code, db)

    # Try cache again after populate
    cached = db.get_ecourts_type_id(state_cd, court_code, prefix)
    if cached:
        return cached

    # Heuristic name match against all stored types
    types = db.list_ecourts_types(state_cd, court_code)
    if not types:
        return None

    type_id = _match_prefix_in_types(prefix, types)
    if type_id:
        log.info(
            "Learned prefix %r → type_id %s for bench %s/%s",
            prefix, type_id, state_cd, court_code,
        )
        db.set_ecourts_type_prefix(state_cd, court_code, type_id, prefix)
        return type_id

    # Final fallback: hardcoded Calcutta Appellate map (state_cd=16, court_code=3)
    if state_cd == "16" and court_code in ("3", "1"):
        try:
            from .ecourts import CASE_TYPE_IDS
            hardcoded = CASE_TYPE_IDS.get(prefix.upper())
            if hardcoded:
                type_id_str = str(hardcoded)
                log.info(
                    "Fallback hardcoded map: %r → %s for bench %s/%s",
                    prefix, type_id_str, state_cd, court_code,
                )
                db.set_ecourts_type_prefix(state_cd, court_code, type_id_str, prefix)
                return type_id_str
        except Exception:
            pass

    log.warning(
        "Could not resolve prefix %r for bench %s/%s", prefix, state_cd, court_code
    )
    return None


def record_learned_prefix(
    state_cd: str, court_code: str, type_id: str, prefix: str, db: Any
) -> None:
    """Persist a confirmed prefix→type_id mapping (call after successful eCourts search)."""
    db.set_ecourts_type_prefix(state_cd, court_code, type_id, prefix)
    log.info(
        "Recorded confirmed prefix %r → %s for bench %s/%s",
        prefix, type_id, state_cd, court_code,
    )

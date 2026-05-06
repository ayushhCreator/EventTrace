"""eCourts Calcutta HC case lookup.

Flow:
  1. GET case_no.php → acquire PHPSESSID cookie
  2. GET securimage_show.php (same session) → CAPTCHA image bytes, answer stored server-side
  3. Send image to Claude claude-haiku-4-5 vision → solve 5-char alphanumeric text
  4. POST case_no_qry.php?action_code=showRecords → HTML result
  5. Parse HTML → case details
  6. Retry up to MAX_TRIES if CAPTCHA rejected
"""
from __future__ import annotations

import base64
import logging
import random
import re
import time
from typing import Any

import requests

log = logging.getLogger(__name__)

_BASE = "https://hcservices.ecourts.gov.in/ecourtindiaHC"
_PAGE_URL = f"{_BASE}/cases/case_no.php?state_cd=16&dist_cd=1&court_code=3&stateNm=Calcutta"
_QRY_URL  = f"{_BASE}/cases/case_no_qry.php"
_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Referer": _PAGE_URL,
}
MAX_TRIES = 3

# eCourts case-type abbrev → numeric ID (Appellate Side, Calcutta HC)
CASE_TYPE_IDS: dict[str, int] = {
    "AD-COM": 73, "AO-COM": 72, "AST": 41, "CCGAT": 38,
    "CO": 15, "CO.CT": 34, "COLRT": 40, "CO.ST": 35, "COT": 27, "CO.TT": 36,
    "CPAN": 13, "CR": 14, "CRA": 11, "CRA (DB)": 55, "CRA (SB)": 54,
    "CRC": 42, "CR-IPD": 68, "CRLCP": 46,
    "CRM": 17, "CRM (A)": 58, "CRM (DB)": 57, "CRM (FEMA)": 62,
    "CRM (FERA)": 61, "CRM(M)": 74, "CRM (NDPS)": 60, "CRM(R)": 75,
    "CRM (SB)": 56, "CRMSPL": 3, "CRM (TADA)": 59,
    "CRR": 16, "DR": 18, "DVW": 1,
    "FA": 9, "FA-IPD": 64, "FAT": 6, "FAT-IPD": 65, "FCA": 30,
    "FMA": 19, "FMA-IPD": 66, "FMAT": 8, "FMAT (ARBAWARD)": 53,
    "FMAT-IPD": 67, "FMAT (IR)": 51, "FMAT (MV)": 52,
    "FMAT (RERA)": 71, "FMAT (WC)": 50,
    "GA": 26, "IRD": 22, "IRE": 23, "IRH": 24,
    "LPA": 2, "MA": 21, "MAT": 25,
    "RVW": 20, "RVW-IPD": 69,
    "SA": 10, "SAT": 7, "SMA": 29, "SMAT": 28,
    "SRC": 4, "SRCR": 5, "TRP(COMM)": 63, "WCGAT": 37,
    "WPA": 12, "WPA(H)": 49, "WPA-IPD": 70, "WPA(P)": 48,
    "WPCR": 44, "WPCRC": 43, "WP.CT": 31, "WPDRT": 47,
    "WPLRT": 39, "WP.ST": 32, "WP.TT": 33, "WP.WT": 45,
}


def _solve_captcha_with_claude(image_bytes: bytes, api_key: str) -> str:
    """Send CAPTCHA image to Claude claude-haiku-4-5 and return the text."""
    import anthropic

    b64 = base64.standard_b64encode(image_bytes).decode()
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": b64},
                },
                {
                    "type": "text",
                    "text": (
                        "This is a CAPTCHA image. It contains exactly 5 alphanumeric characters "
                        "(letters and digits). Reply with ONLY those characters, nothing else. "
                        "No spaces, no punctuation."
                    ),
                },
            ],
        }],
    )
    return msg.content[0].text.strip()


def _parse_result(raw: str) -> list[dict[str, Any]]:
    """Parse eCourts showRecords response.

    Format (tilde-delimited, one record per ##-terminated chunk):
      {internal_id}~{case_ref}~{parties_html}~{cino}~{court_no}~...##
    """
    results = []
    # Each record ends with ## — split on ## and process non-empty chunks
    chunks = [c.strip() for c in raw.split("##") if c.strip()]
    for chunk in chunks:
        parts = chunk.split("~")
        if len(parts) < 3:
            continue

        # Field 1: case_ref  e.g. "WPA/71/2026"
        raw_ref = parts[1].strip()
        ref_m = re.match(r"([A-Z][A-Z0-9.()\- ]*?)\s*/\s*(\d+)\s*/\s*(\d{4})", raw_ref)
        if not ref_m:
            continue
        case_type   = ref_m.group(1).strip()
        case_number = ref_m.group(2)
        case_year   = int(ref_m.group(3))
        case_ref    = f"{case_type}/{case_number}/{case_year}"

        # Field 2: parties HTML  e.g. "RUPA PAUL AND ANR.<br/>Versus<br/>STATE OF WB"
        party_html = parts[2]
        party_text = re.sub(r"<[^>]+>", " ", party_html).strip()
        petitioner = respondent = None
        vs_m = re.split(r"\bversus\b|\bvs\.?\b", party_text, maxsplit=1, flags=re.IGNORECASE)
        if len(vs_m) == 2:
            petitioner = re.sub(r"\s+", " ", vs_m[0]).strip() or None
            respondent = re.sub(r"\s+", " ", vs_m[1]).strip() or None

        # Field 4: court_no (index 4 if present)
        court_no = parts[4].strip() if len(parts) > 4 else None

        results.append({
            "case_ref":    case_ref,
            "case_type":   case_type,
            "case_number": case_number,
            "case_year":   case_year,
            "petitioner":  petitioner,
            "respondent":  respondent,
            "court_no":    court_no or None,
        })
    return results


def lookup_case(case_ref: str, api_key: str) -> dict[str, Any] | None:
    """
    Look up a case on eCourts Calcutta HC.

    Returns a dict with: case_ref, case_type, case_number, case_year,
    petitioner, respondent — or None if not found.
    Raises ValueError for unsupported case type or bad case_ref format.
    Raises RuntimeError if CAPTCHA keeps failing.
    """
    # Parse case_ref
    m = re.match(
        r"^([A-Za-z][A-Za-z0-9.()\-]*)\s*/\s*(\d+)\s*/\s*(\d{4})$",
        case_ref.strip(),
    )
    if not m:
        raise ValueError(f"Invalid case ref format: {case_ref!r}")

    case_type_str  = m.group(1).upper()
    case_number    = m.group(2).lstrip("0") or m.group(2)
    case_year      = m.group(3)

    type_id = CASE_TYPE_IDS.get(case_type_str)
    if not type_id:
        raise ValueError(f"Case type {case_type_str!r} not found in eCourts Appellate Side list")

    session = requests.Session()
    session.headers.update(_HEADERS)

    # Step 1: GET page → acquire PHPSESSID
    try:
        session.get(_PAGE_URL, timeout=15)
    except requests.RequestException as e:
        raise RuntimeError(f"eCourts unreachable: {e}") from e

    last_error = ""
    for attempt in range(1, MAX_TRIES + 1):
        # Step 2: GET fresh CAPTCHA image
        captcha_url = f"{_BASE}/securimage/securimage_show.php?{random.random()}"
        try:
            cap_resp = session.get(captcha_url, timeout=10)
            cap_resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch CAPTCHA: {e}") from e

        # Step 3: Solve with Claude
        try:
            captcha_text = _solve_captcha_with_claude(cap_resp.content, api_key)
            log.debug("CAPTCHA attempt %d: solved as %r", attempt, captcha_text)
        except Exception as e:
            raise RuntimeError(f"Claude CAPTCHA solve failed: {e}") from e

        # Step 4: POST query
        payload = {
            "action_code":      "showRecords",
            "state_code":       "16",
            "dist_code":        "1",
            "court_code":       "3",
            "case_type":        str(type_id),
            "case_no":          case_number,
            "rgyear":           case_year,
            "caseNoType":       "new",
            "displayOldCaseNo": "NO",
            "captcha":          captcha_text,
        }
        try:
            resp = session.post(_QRY_URL, data=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"eCourts query failed: {e}") from e

        html = resp.text.strip()
        log.debug("eCourts response (attempt %d): %.200s", attempt, html)

        if html.lower().startswith("error1"):
            last_error = "invalid_captcha"
            time.sleep(0.5)
            continue
        if html.lower().startswith("error2"):
            raise ValueError("Invalid case number according to eCourts")
        if "errordatalimit" in html.lower():
            raise RuntimeError("eCourts rate limit hit — try again later")
        if html.lower().startswith("error"):
            last_error = html[:50]
            time.sleep(0.5)
            continue

        # Step 5: Parse result
        cases = _parse_result(html)
        if not cases:
            return None
        return cases[0]

    raise RuntimeError(f"CAPTCHA failed {MAX_TRIES} times (last error: {last_error})")

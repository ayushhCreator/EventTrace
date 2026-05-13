"""Test UI for eCourts national HC portal — all 25 High Courts.

Endpoints:
  GET  /ecourts-test                          → HTML test UI
  GET  /ecourts-test/api/case-types           → fetch case types for given HC/bench
  POST /ecourts-test/api/search/case-no       → search by case number (CAPTCHA auto-solved)
  POST /ecourts-test/api/search/cnr           → search by CNR number
"""

from __future__ import annotations

import base64
import html as _html
import os
import random
import re
import time
from typing import Any

import requests
import structlog
from bs4 import BeautifulSoup
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..services.deps import get_db

log = structlog.get_logger()

router = APIRouter(prefix="/ecourts-test", tags=["ecourts-test"])

_BASE = "https://hcservices.ecourts.gov.in/ecourtindiaHC"
_QRY_URL = f"{_BASE}/cases/case_no_qry.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Referer": "https://hcservices.ecourts.gov.in/hcservices/main.php",
}
MAX_TRIES = 3

# All 25 HCs with their known bench codes
HC_BENCHES: dict[str, list[dict]] = {
    "1": [
        {"code": "1", "name": "Principal Bench — Mumbai"},
        {"code": "2", "name": "Bench at Nagpur"},
        {"code": "3", "name": "Bench at Aurangabad"},
        {"code": "4", "name": "Bench at Goa"},
    ],
    "2": [{"code": "1", "name": "Principal Bench — Amaravathi"}],
    "3": [{"code": "1", "name": "Principal Bench — Bengaluru"}],
    "4": [{"code": "1", "name": "Principal Bench — Ernakulam"}],
    "5": [{"code": "1", "name": "Principal Bench — Shimla"}],
    "6": [
        {"code": "1", "name": "Principal Bench — Guwahati"},
        {"code": "2", "name": "Bench at Kohima"},
        {"code": "3", "name": "Bench at Aizawl"},
        {"code": "4", "name": "Bench at Agartala"},
        {"code": "5", "name": "Bench at Imphal"},
    ],
    "7": [{"code": "1", "name": "Principal Bench — Ranchi"}],
    "8": [{"code": "1", "name": "Principal Bench — Patna"}],
    "9": [
        {"code": "1", "name": "Principal Bench — Jodhpur"},
        {"code": "2", "name": "Bench at Jaipur"},
    ],
    "10": [
        {"code": "1", "name": "Principal Bench — Chennai"},
        {"code": "2", "name": "Bench at Madurai"},
    ],
    "11": [{"code": "1", "name": "Principal Bench — Cuttack"}],
    "12": [
        {"code": "1", "name": "Principal Bench — Srinagar"},
        {"code": "2", "name": "Bench at Jammu"},
    ],
    "13": [
        {"code": "1", "name": "Principal Bench — Allahabad"},
        {"code": "2", "name": "Bench at Lucknow"},
    ],
    "15": [{"code": "1", "name": "Principal Bench — Nainital"}],
    "16": [
        {"code": "3", "name": "Appellate Side"},
        {"code": "1", "name": "Original Side"},
        {"code": "2", "name": "Circuit Bench — Jalpaiguri"},
        {"code": "4", "name": "Circuit Bench — Port Blair"},
    ],
    "17": [{"code": "1", "name": "Principal Bench — Ahmedabad"}],
    "18": [{"code": "1", "name": "Principal Bench — Bilaspur"}],
    "20": [{"code": "1", "name": "Principal Bench — Agartala"}],
    "21": [{"code": "1", "name": "Principal Bench — Shillong"}],
    "22": [{"code": "1", "name": "Principal Bench — Chandigarh"}],
    "23": [
        {"code": "1", "name": "Principal Bench — Jabalpur"},
        {"code": "2", "name": "Bench at Gwalior"},
        {"code": "3", "name": "Bench at Indore"},
    ],
    "24": [{"code": "1", "name": "Principal Bench — Gangtok"}],
    "25": [{"code": "1", "name": "Principal Bench — Imphal"}],
    "26": [{"code": "1", "name": "Principal Bench — New Delhi"}],
    "29": [{"code": "1", "name": "Principal Bench — Hyderabad"}],
}

HC_NAMES: dict[str, str] = {
    "1": "Bombay High Court",
    "2": "High Court of Andhra Pradesh",
    "3": "High Court of Karnataka",
    "4": "High Court of Kerala",
    "5": "High Court of Himachal Pradesh",
    "6": "Gauhati High Court",
    "7": "High Court of Jharkhand",
    "8": "Patna High Court",
    "9": "High Court of Rajasthan",
    "10": "Madras High Court",
    "11": "High Court of Orissa",
    "12": "High Court of Jammu and Kashmir",
    "13": "Allahabad High Court",
    "15": "High Court of Uttarakhand",
    "16": "Calcutta High Court",
    "17": "High Court of Gujarat",
    "18": "High Court of Chhattisgarh",
    "20": "High Court of Tripura",
    "21": "High Court of Meghalaya",
    "22": "High Court of Punjab and Haryana",
    "23": "High Court of Madhya Pradesh",
    "24": "High Court of Sikkim",
    "25": "High Court of Manipur",
    "26": "High Court of Delhi",
    "29": "High Court for State of Telangana",
}


def _page_url(state_cd: str, court_code: str) -> str:
    name = HC_NAMES.get(state_cd, "")
    return f"{_BASE}/cases/case_no.php?state_cd={state_cd}&dist_cd=1&court_code={court_code}&stateNm={name}"


def _solve_captcha(image_bytes: bytes, api_key: str) -> str:
    import anthropic

    b64 = base64.standard_b64encode(image_bytes).decode()
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a CAPTCHA image with exactly 5 alphanumeric characters. "
                            "Reply with ONLY those characters, nothing else. No spaces, no punctuation."
                        ),
                    },
                ],
            }
        ],
    )
    return msg.content[0].text.strip()


def _parse_tilde_response(raw: str) -> list[dict[str, Any]]:
    """Parse eCourts tilde-delimited showRecords response."""
    results = []
    for chunk in [c.strip() for c in raw.split("##") if c.strip()]:
        parts = chunk.split("~")
        if len(parts) < 3:
            continue
        internal_id = parts[0].strip()  # DB internal row ID (not CNR — parts[3] is CNR)
        raw_ref = parts[1].strip()
        m = re.match(r"([A-Z][A-Z0-9.()\- ]*?)\s*/\s*(\d+)\s*/\s*(\d{4})", raw_ref)
        if not m:
            continue
        case_type = m.group(1).strip()
        case_number = m.group(2)
        case_year = int(m.group(3))
        case_ref = f"{case_type}/{case_number}/{case_year}"

        party_text = re.sub(r"<[^>]+>", " ", parts[2]).strip()
        vs = re.split(r"\bversus\b|\bvs\.?\b", party_text, maxsplit=1, flags=re.IGNORECASE)
        petitioner = re.sub(r"\s+", " ", vs[0]).strip() or None if len(vs) >= 1 else None
        respondent = re.sub(r"\s+", " ", vs[1]).strip() or None if len(vs) == 2 else None

        cnr = parts[3].strip() if len(parts) > 3 else None
        court_no = parts[4].strip() if len(parts) > 4 else None
        token = parts[7].strip() if len(parts) > 7 else None

        results.append(
            {
                "internal_id": internal_id or None,
                "case_ref": case_ref,
                "case_type": case_type,
                "case_number": case_number,
                "case_year": case_year,
                "petitioner": petitioner,
                "respondent": respondent,
                "cnr": cnr or None,
                "court_no": court_no or None,
                "token": token or None,
            }
        )
    return results


def _do_case_history(
    state_cd: str,
    court_code: str,
    case_type_id: str,
    case_no: str,
    year: str,
    target_cino: str,
    api_key: str,
) -> dict[str, Any]:
    """Fetch case history via combined showRecords+o_civil_case_history.php in one session."""
    page_url = _page_url(state_cd, court_code)
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Referer": page_url, "X-Requested-With": "XMLHttpRequest"})
    sess.get(page_url, timeout=15)

    last_error = ""
    for attempt in range(1, MAX_TRIES + 1):
        cap_url = f"{_BASE}/securimage/securimage_show.php?{random.random()}"
        try:
            cap_resp = sess.get(cap_url, timeout=10)
            cap_resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"CAPTCHA fetch failed: {e}") from e

        captcha = _solve_captcha(cap_resp.content, api_key)
        log.debug("case_history captcha attempt %d: %r", attempt, captcha)

        # Step 1: showRecords to get internal case_no + token
        payload = {
            "action_code": "showRecords",
            "state_code": state_cd,
            "dist_code": "1",
            "court_code": court_code,
            "case_type": case_type_id,
            "case_no": case_no.lstrip("0") or case_no,
            "rgyear": year,
            "captcha": captcha,
        }
        try:
            resp = sess.post(_QRY_URL, data=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"eCourts search failed: {e}") from e

        raw = resp.text.strip().lstrip("﻿")
        log.debug("case_history showRecords (attempt %d): %.300s", attempt, raw)

        if raw.lower().startswith("error1"):
            last_error = "invalid_captcha"
            time.sleep(0.5)
            continue
        if raw.lower().startswith("error2"):
            raise ValueError("Invalid case number")
        if raw.lower().startswith("error"):
            last_error = raw[:60]
            time.sleep(0.5)
            continue

        results = _parse_tilde_response(raw)
        if not results:
            raise ValueError("Case not found in search results")

        # Pick result matching target_cino (or first result)
        match = next(
            (r for r in results if r.get("cnr") == target_cino.upper()),
            results[0],
        )
        internal_case_no = match["internal_id"]
        token = match.get("token", "")
        court_code_r = match.get("court_no") or court_code

        if not internal_case_no or not token:
            raise ValueError("Search result missing internal ID or token")

        # Step 2: fetch history in same session
        try:
            hist_resp = sess.post(
                f"{_BASE}/cases/o_civil_case_history.php",
                data={
                    "court_code": court_code_r,
                    "state_code": state_cd,
                    "dist_code": "1",
                    "case_no": internal_case_no,
                    "cino": target_cino.upper(),
                    "token": token,
                    "appFlag": "",
                },
                timeout=15,
            )
            hist_resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"History fetch failed: {e}") from e

        hist_raw = hist_resp.text
        log.debug("case_history o_civil len=%d", len(hist_raw))
        result = _parse_case_history(hist_raw, target_cino.upper())

        # Fetch order PDFs in same session (session cookies still valid)
        for order in result.get("orders", []):
            pdf_url = order.get("pdf_url")
            if not pdf_url:
                continue
            try:
                pdf_resp = sess.get(pdf_url, timeout=15)
                ct = pdf_resp.headers.get("content-type", "")
                if pdf_resp.ok and "pdf" in ct.lower():
                    order["pdf_b64"] = base64.standard_b64encode(pdf_resp.content).decode()
                    log.debug("pdf fetched order=%s size=%d", order.get("number"), len(pdf_resp.content))
            except Exception as pdf_err:
                log.debug("pdf_fetch skip: %s", pdf_err)

        return result

    raise RuntimeError(f"CAPTCHA failed {MAX_TRIES} times (last: {last_error})")


def _parse_case_history(raw: str, cino: str) -> dict[str, Any]:
    """Parse getCaseHistory HTML response into structured JSON."""
    if "<table" not in raw.lower() and "<tr" not in raw.lower():
        # Tilde/hash delimited fallback
        hearings = []
        for chunk in [c.strip() for c in raw.split("##") if c.strip()]:
            parts = chunk.split("~")
            if len(parts) >= 2:
                hearings.append(
                    {
                        "date": parts[0].strip(),
                        "purpose": parts[1].strip(),
                        "judge": parts[2].strip() if len(parts) > 2 else None,
                        "next": parts[3].strip() if len(parts) > 3 else None,
                    }
                )
        return {"cino": cino, "format": "tilde", "hearings": hearings}

    soup = BeautifulSoup(raw, "html.parser")
    log.debug("parse_case_history html_len=%d", len(raw))

    def _text(tag) -> str:
        if not tag:
            return ""
        return _html.unescape(tag.get_text(" ", strip=True))

    # ── Content-fingerprint table classifier ─────────────────────────────────
    # Walk every table once; identify it by keywords in its text content.
    # This is resilient to CSS class name changes and heading-proximity bugs.

    case_details: dict[str, str] = {}
    case_status: dict[str, str] = {}
    acts: list[dict] = []
    sub_court: dict[str, str] = {}
    hearings: list[dict] = []
    orders: list[dict] = []
    category: dict[str, str] = {}
    objections: list[dict] = []
    documents: list[dict] = []

    def _kv_table(tbl) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in tbl.find_all("tr"):
            cells = row.find_all(["td", "th"])
            for i in range(0, len(cells) - 1, 2):
                label = _text(cells[i]).rstrip(":").strip()
                value = _text(cells[i + 1]).strip()
                if label and value:
                    result[label] = value
        return result

    def _tbl_text(tbl) -> str:
        return tbl.get_text(" ", strip=True).lower()

    for tbl in soup.find_all("table"):
        t = _tbl_text(tbl)

        # ── Case Details: has CNR number ──────────────────────────────────
        if not case_details and "cnr" in t and ("filing" in t or "registration" in t):
            case_details = _kv_table(tbl)

        # ── Case Status: has "first hearing date" or "stage of case" ─────
        elif not case_status and ("first hearing" in t or "stage of case" in t or "next hearing" in t):
            for row in tbl.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    label = _text(cells[0]).rstrip(":")
                    value = _text(cells[1])
                    if label:
                        case_status[label] = value
                elif len(cells) == 1:
                    raw = _text(cells[0])
                    if ":" in raw:
                        label, _, value = raw.partition(":")
                        if label.strip():
                            case_status[label.strip()] = value.strip()

        # ── Acts: has "under act" header ──────────────────────────────────
        elif not acts and "under act" in t:
            rows = tbl.find_all("tr")
            start = 1 if rows and "under act" in _text(rows[0]).lower() else 0
            for row in rows[start:]:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    act_val = _text(cells[0])
                    sec_val = _text(cells[1])
                    if act_val or sec_val:
                        acts.append({"act": act_val, "section": sec_val})

        # ── Subordinate Court: has "court number and name" or "district" ──
        elif not sub_court and ("court number and name" in t or ("district" in t and "state" in t and "case decision" in t)):
            for row in tbl.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    label = _text(cells[0]).rstrip(":")
                    value = _text(cells[1])
                    if label:
                        sub_court[label] = value

        # ── Hearing History: has "cause list type" and "purpose of hearing" ──
        elif not hearings and "cause list type" in t and "purpose" in t:
            for row in tbl.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue
                cause_list_type = _text(cells[0])
                if cause_list_type == "Order Number":
                    break
                purpose = _text(cells[4]) if len(cells) > 4 else ""
                if purpose == "View":
                    continue
                biz_link = cells[2].find("a")
                biz_date = _text(biz_link) if biz_link else _text(cells[2])
                hearings.append({
                    "cause_list_type": cause_list_type,
                    "judge": _text(cells[1]),
                    "business_on": biz_date,
                    "hearing_date": _text(cells[3]),
                    "purpose": purpose,
                })

        # ── Orders: has "order number" and "order date" ───────────────────
        elif not orders and "order number" in t and "order date" in t:
            for row in tbl.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue
                pdf_link = cells[4].find("a") if len(cells) > 4 else None
                href = pdf_link.get("href", "") if pdf_link else ""
                pdf_url = (
                    f"https://hcservices.ecourts.gov.in/ecourtindiaHC/{href.lstrip('/')}"
                    if href else None
                )
                orders.append({
                    "number": _text(cells[0]),
                    "case": _text(cells[1]),
                    "judge": _text(cells[2]),
                    "date": _text(cells[3]),
                    "pdf_url": pdf_url,
                })

        # ── Category: has "category" and "sub category" ───────────────────
        elif not category and "sub category" in t and len(t) < 300:
            category = _kv_table(tbl)

        # ── Objections: has "scrutiny date" ───────────────────────────────
        elif not objections and "scrutiny date" in t:
            rows = tbl.find_all("tr")
            if rows:
                hdrs = [_text(c) for c in rows[0].find_all(["th", "td"])]
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if cells:
                        objections.append({hdrs[i]: _text(cells[i]) for i in range(min(len(hdrs), len(cells)))})

        # ── Documents: has "document no" and "filed by" ───────────────────
        elif not documents and "document no" in t and "filed by" in t:
            rows = tbl.find_all("tr")
            if rows:
                hdrs = [_text(c) for c in rows[0].find_all(["th", "td"])]
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if cells:
                        documents.append({hdrs[i]: _text(cells[i]) for i in range(min(len(hdrs), len(cells)))})

    # ── Parties (span-based, unchanged) ───────────────────────────────────────
    def _party_lines(cls: str) -> list[str]:
        span = soup.find("span", class_=cls)
        if not span:
            return []
        for br in span.find_all("br"):
            br.replace_with("\n")
        lines = [_html.unescape(l.strip()) for l in span.get_text().split("\n")]
        return [l for l in lines if l]

    def _party_lines_any(classes: list[str]) -> list[str]:
      for cls in classes:
        lines = _party_lines(cls)
        if lines:
          return lines
      return []

    petitioners = _party_lines_any([
      "Petitioner",
      "petitioner",
      "Petitioner_Name",
      "petitioner_name",
    ])
    respondents = _party_lines_any([
      "Respondent",
      "respondent",
      "Respondent_Name",
      "respondent_name",
    ])

    return {
        "cino": cino,
        "format": "structured",
        "case_details": case_details,
        "case_status": case_status,
        "petitioners": petitioners,
        "respondents": respondents,
        "acts": acts,
        "sub_court": sub_court,
        "hearings": hearings,
        "orders": orders,
        "category": category,
        "objections": objections,
        "documents": documents,
    }


def _do_case_search(
    state_cd: str,
    court_code: str,
    case_type_id: str,
    case_no: str,
    year: str,
    api_key: str,
) -> list[dict[str, Any]]:
    page_url = _page_url(state_cd, court_code)
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Referer": page_url})
    sess.get(page_url, timeout=15)

    last_error = ""
    for attempt in range(1, MAX_TRIES + 1):
        cap_url = f"{_BASE}/securimage/securimage_show.php?{random.random()}"
        cap_resp = sess.get(cap_url, timeout=10)
        cap_resp.raise_for_status()
        captcha = _solve_captcha(cap_resp.content, api_key)
        log.debug("ecourts_test captcha attempt %d: %r", attempt, captcha)

        payload = {
            "action_code": "showRecords",
            "state_code": state_cd,
            "dist_code": "1",
            "court_code": court_code,
            "case_type": case_type_id,
            "case_no": case_no.lstrip("0") or case_no,
            "rgyear": year,
            "captcha": captcha,
        }
        resp = sess.post(_QRY_URL, data=payload, timeout=15)
        resp.raise_for_status()
        html = resp.text.strip()

        if html.lower().startswith("error1"):
            last_error = "invalid_captcha"
            time.sleep(0.5)
            continue
        if html.lower().startswith("error2"):
            raise ValueError("Invalid case number per eCourts")
        if "errordatalimit" in html.lower():
            raise RuntimeError("eCourts rate limit — try again later")
        if html.lower().startswith("error"):
            last_error = html[:60]
            time.sleep(0.5)
            continue

        return _parse_tilde_response(html)

    raise RuntimeError(f"CAPTCHA failed {MAX_TRIES} times (last: {last_error})")


def _decode_cnr(cnr: str) -> tuple[str, str] | None:
    """Decode state_cd and court_code from a HC CNR string.

    HC CNRs: WBCH... → WB=West Bengal(16), CH=Calcutta HC(court_code 3)
    Returns (state_cd, court_code) or None if unknown.
    """
    # Map of 2-char state prefix in CNR → state_cd
    _STATE = {
        "WB": "16",
        "MH": "1",
        "AP": "2",
        "KA": "3",
        "KL": "4",
        "HP": "5",
        "AS": "6",
        "JH": "7",
        "BR": "8",
        "RJ": "9",
        "TN": "10",
        "OR": "11",
        "JK": "12",
        "UP": "13",
        "UT": "15",
        "GJ": "17",
        "CG": "18",
        "TR": "20",
        "ML": "21",
        "PB": "22",
        "MP": "23",
        "SK": "24",
        "MN": "25",
        "DL": "26",
        "TS": "29",
    }
    if len(cnr) < 4:
        return None
    state_prefix = cnr[:2].upper()
    state_cd = _STATE.get(state_prefix)
    if not state_cd:
        return None
    # For now assume principal/appellate bench (code 3 for Calcutta, 1 for others)
    court_code = "3" if state_cd == "16" else "1"
    return (state_cd, court_code)


def _do_cnr_search(
    cnr: str,
    state_cd: str,
    court_code: str,
    api_key: str,
) -> dict[str, Any] | None:
    """CNR lookup: fetches all case types for the bench, then tries each type with one CAPTCHA.

    HC portals have no direct CNR endpoint.  Strategy:
    1. fillCaseType (no CAPTCHA) to get list of type IDs
    2. Prioritise types whose abbreviation starts with CNR chars[4:6]
    3. For each type: solve CAPTCHA → showRecords (year from CNR) → check if any result CNR matches
    4. On first match: fetch history in same session and return
    """
    cnr = cnr.upper().strip()
    cnr_year = cnr[12:16] if len(cnr) >= 16 else ""
    cnr_type = cnr[4:6] if len(cnr) >= 6 else ""

    page_url = _page_url(state_cd, court_code)
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Referer": page_url, "X-Requested-With": "XMLHttpRequest"})
    try:
        sess.get(page_url, timeout=15)
    except requests.RequestException as e:
        raise RuntimeError(f"eCourts unreachable: {e}") from e

    # Get case types (no CAPTCHA needed)
    try:
        types_resp = sess.post(
            _QRY_URL,
            data={
                "action_code": "fillCaseType",
                "state_code": state_cd,
                "dist_code": "1",
                "court_code": court_code,
            },
            timeout=15,
        )
        raw_types = types_resp.text.lstrip("﻿")
    except requests.RequestException:
        raw_types = ""

    all_types: list[tuple[str, str]] = []
    for chunk in raw_types.split("#"):
        if chunk and "~" in chunk:
            id_v, _, name = chunk.partition("~")
            id_v = id_v.strip()
            if id_v and id_v != "0":
                all_types.append((id_v, name.strip()))

    # Sort: types whose name starts with cnr_type come first
    def _priority(t: tuple[str, str]) -> int:
        return 0 if t[1].startswith(cnr_type) else 1

    sorted_types = sorted(all_types, key=_priority)
    MAX_TYPE_TRIES = 10

    for type_id, type_name in sorted_types[:MAX_TYPE_TRIES]:
        # Fresh CAPTCHA per case type
        try:
            cap_resp = sess.get(
                f"{_BASE}/securimage/securimage_show.php?{random.random()}", timeout=10
            )
            cap_resp.raise_for_status()
        except requests.RequestException:
            continue

        captcha = _solve_captcha(cap_resp.content, api_key)
        log.debug("cnr_search type=%s/%s captcha=%r", type_id, type_name[:20], captcha)

        try:
            resp = sess.post(
                _QRY_URL,
                data={
                    "action_code": "showRecords",
                    "state_code": state_cd,
                    "dist_code": "1",
                    "court_code": court_code,
                    "case_type": type_id,
                    "case_no": "1",
                    "rgyear": cnr_year,  # year-only search with dummy no
                    "captcha": captcha,
                },
                timeout=15,
            )
        except requests.RequestException:
            continue

        raw = resp.text.strip().lstrip("﻿")
        if raw.lower().startswith("error"):
            time.sleep(0.3)
            continue

        results = _parse_tilde_response(raw)
        match = next((r for r in results if r.get("cnr") == cnr), None)
        if not match:
            continue

        # Found — fetch history in same session
        internal_no = match["internal_id"]
        token = match.get("token", "")
        if not internal_no or not token:
            return match  # return search result at least

        try:
            hist_resp = sess.post(
                f"{_BASE}/cases/o_civil_case_history.php",
                data={
                    "court_code": match.get("court_no") or court_code,
                    "state_code": state_cd,
                    "dist_code": "1",
                    "case_no": internal_no,
                    "cino": cnr,
                    "token": token,
                    "appFlag": "",
                },
                timeout=15,
            )
            return _parse_case_history(hist_resp.text, cnr)
        except requests.RequestException:
            return match

    return None


# ── API endpoints ────────────────────────────────────────────────────────────


@router.get("/api/benches")
async def get_benches(state_cd: str):
    benches = HC_BENCHES.get(state_cd, [{"code": "1", "name": "Principal Bench"}])
    return {"benches": benches}


@router.get("/api/case-types")
async def get_case_types(state_cd: str, court_code: str):
    """Fetch case type list via fillCaseType action on case_no_qry.php."""
    page_url = _page_url(state_cd, court_code)
    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Referer": page_url, "X-Requested-With": "XMLHttpRequest"})
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
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    raw = r.text.strip().lstrip("﻿")  # strip BOM
    if not raw:
        return JSONResponse({"error": "Empty response from eCourts"}, status_code=502)

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

    return {"case_types": types}


@router.post("/api/search/case-no")
async def search_by_case_no(request: Request):
    body = await request.json()
    state_cd = str(body.get("state_cd", ""))
    court_code = str(body.get("court_code", ""))
    case_type_id = str(body.get("case_type_id", ""))
    case_no = str(body.get("case_no", "")).strip()
    year = str(body.get("year", "")).strip()

    if not all([state_cd, court_code, case_type_id, case_no, year]):
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    settings = request.app.state.settings
    api_key = getattr(settings, "anthropic_api_key", None) or __import__("os").getenv(
        "ANTHROPIC_API_KEY", ""
    )
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=500)

    try:
        results = _do_case_search(state_cd, court_code, case_type_id, case_no, year, api_key)
        return {"results": results, "count": len(results)}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        log.error("case_search error", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/case-history")
async def get_case_history(request: Request):
    body = await request.json()
    cino = str(body.get("cino", "")).strip()
    state_cd = str(body.get("state_cd", "")).strip()
    court_code = str(body.get("court_code", "")).strip()
    case_type_id = str(body.get("case_type_id", "")).strip()
    case_no = str(body.get("case_no", "")).strip()
    year = str(body.get("year", "")).strip()

    if not all([cino, state_cd, court_code, case_type_id, case_no, year]):
        return JSONResponse(
            {
                "error": "Missing required fields: cino, state_cd, court_code, case_type_id, case_no, year"
            },
            status_code=400,
        )

    settings = request.app.state.settings
    api_key = getattr(settings, "anthropic_api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=500)

    db = get_db(request)
    ttl_seconds = int(os.getenv("CASE_HISTORY_CACHE_TTL_SECONDS", "3600"))
    try:
      cached = db.get_case_history_cache(cino, state_cd, court_code, ttl_seconds)
      if cached:
        return cached
    except Exception as exc:
      log.warning("case_history cache lookup failed: %s", exc)

    try:
        result = _do_case_history(state_cd, court_code, case_type_id, case_no, year, cino, api_key)
        try:
            db.set_case_history_cache(cino, state_cd, court_code, case_type_id, case_no, year, result)
        except Exception as exc:
            log.warning("case_history cache write failed: %s", exc)
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        log.error("case_history error", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/search/cnr")
async def search_by_cnr(request: Request):
    body = await request.json()
    cnr = str(body.get("cnr", "")).strip()
    state_cd = str(body.get("state_cd", "")).strip()
    court_code = str(body.get("court_code", "")).strip()

    if not cnr or len(cnr) != 16:
        return JSONResponse({"error": "CNR must be exactly 16 characters"}, status_code=400)

    # Auto-decode state from CNR if not provided
    if not state_cd:
        decoded = _decode_cnr(cnr)
        if decoded:
            state_cd, court_code = decoded
        else:
            return JSONResponse(
                {"error": "Cannot determine HC from CNR. Please select HC and bench."},
                status_code=400,
            )
    if not court_code:
        court_code = "3" if state_cd == "16" else "1"

    settings = request.app.state.settings
    api_key = getattr(settings, "anthropic_api_key", None) or __import__("os").getenv(
        "ANTHROPIC_API_KEY", ""
    )
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=500)

    try:
        result = _do_cnr_search(cnr, state_cd, court_code, api_key)
        if result is None:
            return JSONResponse(
                {
                    "error": "Case not found. The CNR may belong to a different bench — try selecting a different bench."
                },
                status_code=404,
            )
        return result
    except Exception as e:
        log.error("cnr_search error", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=502)


# ── HTML test UI ─────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>eCourts HC Test — All India</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
  body { background: #f0f4f8; font-family: 'Segoe UI', sans-serif; }
  .sidebar { background: #1a3c5e; min-height: 100vh; padding: 0; }
  .sidebar-header { background: #122d47; padding: 18px 12px; text-align:center; color:#fff; font-size:1.1rem; font-weight:600; letter-spacing:.5px; }
  .tab-btn { display:block; width:100%; text-align:left; padding:14px 18px; background:transparent; border:none; border-bottom:1px solid rgba(255,255,255,.08); color:rgba(255,255,255,.75); font-size:.92rem; cursor:pointer; transition:background .2s; }
  .tab-btn:hover, .tab-btn.active { background:rgba(255,255,255,.12); color:#fff; }
  .tab-btn i { width:20px; margin-right:8px; }
  .main-panel { padding: 28px; }
  .card { border:none; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,.08); }
  .card-header { background:#1a3c5e; color:#fff; border-radius:12px 12px 0 0 !important; padding:14px 20px; font-weight:600; }
  .result-table th { background:#1a3c5e; color:#fff; font-size:.82rem; }
  .result-table td { font-size:.85rem; vertical-align:middle; }
  .badge-cnr { background:#0d6efd; font-size:.75rem; font-family:monospace; }
  .spinner-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:9999; align-items:center; justify-content:center; }
  .spinner-overlay.show { display:flex; }
  .hc-select-row { background:#fff; border-radius:10px; padding:16px 20px; box-shadow:0 1px 6px rgba(0,0,0,.07); margin-bottom:20px; }
  select, input[type=text], input[type=number] { border-radius:6px !important; }
  .form-section { display:none; }
  .form-section.active { display:block; }
  #results-area { display:none; }
</style>
</head>
<body>

<div class="spinner-overlay" id="spinner">
  <div class="text-center text-white">
    <div class="spinner-border mb-3" style="width:3rem;height:3rem;"></div>
    <div id="spinner-msg">Solving CAPTCHA &amp; querying eCourts…</div>
  </div>
</div>

<div class="row g-0">
  <!-- Sidebar -->
  <div class="col-md-2 sidebar">
    <div class="sidebar-header"><i class="fa fa-scale-balanced me-2"></i>eCourts HC Test</div>
    <button class="tab-btn active" onclick="switchTab('case-no')"><i class="fa fa-hashtag"></i>Case Number</button>
    <button class="tab-btn" onclick="switchTab('party')"><i class="fa fa-users"></i>Party Name<span class="badge bg-secondary ms-1" style="font-size:.65rem">Soon</span></button>
    <button class="tab-btn" onclick="switchTab('orders')"><i class="fa fa-file-pdf"></i>Court Orders<span class="badge bg-secondary ms-1" style="font-size:.65rem">Soon</span></button>
    <hr style="border-color:rgba(255,255,255,.15);margin:8px 0">
    <div style="padding:12px 18px;color:rgba(255,255,255,.45);font-size:.78rem;">
      CAPTCHA auto-solved via Claude Haiku. ~2–5s per query.
    </div>
  </div>

  <!-- Main -->
  <div class="col-md-10 main-panel">

    <!-- HC + Bench selector (always visible) -->
    <div class="hc-select-row">
      <div class="row g-3 align-items-end">
        <div class="col-md-5">
          <label class="form-label fw-semibold mb-1">High Court</label>
          <select class="form-select" id="hc-select" onchange="onHCChange()">
            <option value="">— Select High Court —</option>
            <option value="13">Allahabad High Court</option>
            <option value="1">Bombay High Court</option>
            <option value="16" selected>Calcutta High Court</option>
            <option value="6">Gauhati High Court</option>
            <option value="29">High Court for State of Telangana</option>
            <option value="2">High Court of Andhra Pradesh</option>
            <option value="18">High Court of Chhattisgarh</option>
            <option value="26">High Court of Delhi</option>
            <option value="17">High Court of Gujarat</option>
            <option value="5">High Court of Himachal Pradesh</option>
            <option value="12">High Court of Jammu and Kashmir</option>
            <option value="7">High Court of Jharkhand</option>
            <option value="3">High Court of Karnataka</option>
            <option value="4">High Court of Kerala</option>
            <option value="23">High Court of Madhya Pradesh</option>
            <option value="25">High Court of Manipur</option>
            <option value="21">High Court of Meghalaya</option>
            <option value="11">High Court of Orissa</option>
            <option value="22">High Court of Punjab and Haryana</option>
            <option value="9">High Court of Rajasthan</option>
            <option value="24">High Court of Sikkim</option>
            <option value="20">High Court of Tripura</option>
            <option value="15">High Court of Uttarakhand</option>
            <option value="10">Madras High Court</option>
            <option value="8">Patna High Court</option>
          </select>
        </div>
        <div class="col-md-4">
          <label class="form-label fw-semibold mb-1">Bench</label>
          <select class="form-select" id="bench-select" onchange="onBenchChange()">
            <option value="">— Select Bench —</option>
          </select>
        </div>
        <div class="col-md-3">
          <div id="hc-status" class="text-muted" style="font-size:.82rem;"></div>
        </div>
      </div>
    </div>

    <!-- Case Number Form -->
    <div class="form-section active" id="form-case-no">
      <div class="card mb-3">
        <div class="card-header"><i class="fa fa-hashtag me-2"></i>Search by Case Number</div>
        <div class="card-body">
          <div class="row g-3">
            <div class="col-md-5">
              <label class="form-label">Case Type</label>
              <select class="form-select" id="case-type-select">
                <option value="">— Select HC &amp; Bench first —</option>
              </select>
            </div>
            <div class="col-md-3">
              <label class="form-label">Case Number</label>
              <input type="text" class="form-control" id="case-no-input" placeholder="e.g. 71" maxlength="7">
            </div>
            <div class="col-md-2">
              <label class="form-label">Year</label>
              <input type="text" class="form-control" id="year-input" placeholder="2026" maxlength="4" value="2026">
            </div>
            <div class="col-md-2 d-flex align-items-end">
              <button class="btn btn-primary w-100" onclick="searchCaseNo()">
                <i class="fa fa-search me-1"></i>Search
              </button>
            </div>
          </div>
          <div id="case-no-error" class="alert alert-danger mt-3" style="display:none;"></div>
        </div>
      </div>
    </div>


    <!-- Soon forms -->
    <div class="form-section" id="form-party">
      <div class="alert alert-warning"><i class="fa fa-clock me-2"></i>Party Name search coming soon.</div>
    </div>
    <div class="form-section" id="form-orders">
      <div class="alert alert-warning"><i class="fa fa-clock me-2"></i>Court Orders search coming soon.</div>
    </div>

    <!-- Results -->
    <div id="results-area">
      <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
          <span><i class="fa fa-list me-2"></i>Results <span id="results-count" class="badge bg-light text-dark ms-1"></span></span>
          <button class="btn btn-sm btn-outline-light" onclick="clearResults()"><i class="fa fa-xmark"></i></button>
        </div>
        <div class="card-body p-0">
          <div class="table-responsive">
            <table class="table result-table mb-0">
              <thead id="results-thead"></thead>
              <tbody id="results-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

  </div>
</div>

<!-- History Modal -->
<div class="modal fade" id="historyModal" tabindex="-1">
  <div class="modal-dialog modal-xl modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header" style="background:#1a3c5e;color:#fff;">
        <h5 class="modal-title"><i class="fa fa-clock-rotate-left me-2"></i><span id="modal-case-ref"></span> — Case History</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body" id="modal-body">
        <div class="text-center py-5">
          <div class="spinner-border text-primary mb-3"></div>
          <div class="text-muted">Solving CAPTCHA &amp; fetching history…</div>
        </div>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const BASE = '/ecourts-test';

// ── Tab switching ────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.form-section').forEach(f => f.classList.remove('active'));
  document.querySelector(`[onclick="switchTab('${name}')"]`).classList.add('active');
  document.getElementById(`form-${name}`).classList.add('active');
  clearResults();
}

// ── HC / Bench / Case type cascade ──────────────────────────────────────────
async function onHCChange() {
  const hc = document.getElementById('hc-select').value;
  const benchSel = document.getElementById('bench-select');
  const caseSel  = document.getElementById('case-type-select');

  benchSel.innerHTML = '<option value="">Loading...</option>';
  caseSel.innerHTML  = '<option value="">-- Select Bench first --</option>';

  if (!hc) {
    benchSel.innerHTML = '<option value="">-- Select Bench --</option>';
    return;
  }

  try {
    const res = await fetch(`${BASE}/api/benches?state_cd=${hc}`);
    const data = await res.json();
    benchSel.innerHTML = '<option value="">-- Select Bench --</option>';
    data.benches.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.code;
      opt.textContent = b.name;
      benchSel.appendChild(opt);
    });
    if (data.benches.length === 1) {
      benchSel.value = data.benches[0].code;
      onBenchChange();
    }
  } catch(e) {
    benchSel.innerHTML = '<option value="">-- Failed to load --</option>';
    console.error('onHCChange error:', e);
  }
}

async function onBenchChange() {
  const hc    = document.getElementById('hc-select').value;
  const bench = document.getElementById('bench-select').value;
  const caseSel = document.getElementById('case-type-select');
  const status  = document.getElementById('hc-status');

  caseSel.innerHTML = '<option value="">Loading case types…</option>';
  status.innerHTML  = '<span class="text-warning"><i class="fa fa-spinner fa-spin me-1"></i>Fetching…</span>';

  if (!hc || !bench) {
    caseSel.innerHTML = '<option value="">— Select Bench first —</option>';
    status.innerHTML  = '';
    return;
  }

  try {
    const res  = await fetch(`${BASE}/api/case-types?state_cd=${hc}&court_code=${bench}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    caseSel.innerHTML = '<option value="">— Select Case Type —</option>';
    data.case_types.forEach(ct => {
      const opt = document.createElement('option');
      opt.value = ct.id;
      opt.textContent = ct.name;
      caseSel.appendChild(opt);
    });
    status.innerHTML = `<span class="text-success"><i class="fa fa-check me-1"></i>${data.case_types.length} case types</span>`;
  } catch(e) {
    caseSel.innerHTML = '<option value="">Failed to load</option>';
    status.innerHTML  = `<span class="text-danger"><i class="fa fa-xmark me-1"></i>${e.message}</span>`;
  }
}

// ── Search by Case Number ────────────────────────────────────────────────────
async function searchCaseNo() {
  const hc      = document.getElementById('hc-select').value;
  const bench   = document.getElementById('bench-select').value;
  const typeId  = document.getElementById('case-type-select').value;
  const caseNo  = document.getElementById('case-no-input').value.trim();
  const year    = document.getElementById('year-input').value.trim();
  const errDiv  = document.getElementById('case-no-error');

  errDiv.style.display = 'none';

  if (!hc || !bench)   { showErr(errDiv, 'Select High Court and Bench first.'); return; }
  if (!typeId)         { showErr(errDiv, 'Select a Case Type.'); return; }
  if (!caseNo || !year){ showErr(errDiv, 'Enter Case Number and Year.'); return; }

  showSpinner('Solving CAPTCHA &amp; searching case on eCourts…');
  try {
    const res  = await fetch(`${BASE}/api/search/case-no`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({state_cd: hc, court_code: bench, case_type_id: typeId, case_no: caseNo, year}),
    });
    let data;
    try { data = await res.json(); } catch(_) { data = {error: `Server error ${res.status}`}; }
    if (!res.ok) { showErr(errDiv, data.error || 'Search failed'); return; }
    renderCaseResults(data.results, data.count);
  } catch(e) {
    showErr(errDiv, e.message);
  } finally {
    hideSpinner();
  }
}

// ── Search by CNR ────────────────────────────────────────────────────────────
function onCNRInput() {
  const cnr = document.getElementById('cnr-input').value.trim().toUpperCase();
  if (cnr.length >= 2) {
    const _STATE = {WB:'16',MH:'1',AP:'2',KA:'3',KL:'4',HP:'5',AS:'6',JH:'7',BR:'8',RJ:'9',
                    TN:'10',OR:'11',JK:'12',UP:'13',UT:'15',GJ:'17',CG:'18',TR:'20',ML:'21',
                    PB:'22',MP:'23',SK:'24',MN:'25',DL:'26',TS:'29'};
    const state_cd = _STATE[cnr.slice(0,2)];
    if (state_cd) {
      document.getElementById('cnr-hc-select').value = state_cd;
      onCNRHCChange();
    }
  }
}

async function onCNRHCChange() {
  const hc = document.getElementById('cnr-hc-select').value;
  const benchSel = document.getElementById('cnr-bench-select');
  benchSel.innerHTML = '<option value="">Loading…</option>';
  try {
    const res = await fetch(`${BASE}/api/benches?state_cd=${hc}`);
    const data = await res.json();
    benchSel.innerHTML = data.benches.map(b => `<option value="${b.code}">${b.name}</option>`).join('');
  } catch(_) {
    benchSel.innerHTML = '<option value="1">Principal Bench</option>';
  }
}

async function searchCNR() {
  const cnr        = document.getElementById('cnr-input').value.trim().toUpperCase();
  const state_cd   = document.getElementById('cnr-hc-select').value;
  const court_code = document.getElementById('cnr-bench-select').value;
  const errDiv     = document.getElementById('cnr-error');
  errDiv.style.display = 'none';

  if (cnr.length !== 16) { showErr(errDiv, 'CNR must be exactly 16 characters.'); return; }

  showSpinner('Searching case types for CNR match… (may take a few seconds)');
  try {
    const res  = await fetch(`${BASE}/api/search/cnr`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cnr, state_cd, court_code}),
    });
    let data;
    try { data = await res.json(); } catch(_) { data = {error: `Server error ${res.status}`}; }
    if (!res.ok) { showErr(errDiv, data.error || 'CNR search failed'); return; }
    renderCNRResult(data, cnr);
  } catch(e) {
    showErr(errDiv, e.message);
  } finally {
    hideSpinner();
  }
}

// ── Render results ───────────────────────────────────────────────────────────
function renderCaseResults(results, count) {
  const area  = document.getElementById('results-area');
  const thead = document.getElementById('results-thead');
  const tbody = document.getElementById('results-tbody');
  document.getElementById('results-count').textContent = count + ' result(s)';

  thead.innerHTML = `<tr>
    <th>#</th><th>Case Ref</th><th>Petitioner</th><th>Respondent</th>
    <th>Court No.</th><th>CNR</th><th></th>
  </tr>`;

  tbody.innerHTML = '';
  if (!results.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No cases found.</td></tr>';
  } else {
    const hc         = document.getElementById('hc-select').value;
    const bench      = document.getElementById('bench-select').value;
    const caseTypeId = document.getElementById('case-type-select').value;
    results.forEach((r, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${i+1}</td>
        <td><strong>${esc(r.case_ref)}</strong></td>
        <td>${esc(r.petitioner || '-')}</td>
        <td>${esc(r.respondent || '-')}</td>
        <td>${esc(r.court_no || '-')}</td>
        <td>${r.cnr ? '<span class="badge badge-cnr">' + esc(r.cnr) + '</span>' : '-'}</td>
        <td></td>`;
      if (r.cnr && r.internal_id) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-sm btn-outline-primary';
        btn.innerHTML = '<i class="fa fa-clock-rotate-left me-1"></i>History';
        btn.addEventListener('click', () => viewHistory(
          r.cnr, hc, bench, r.case_ref,
          caseTypeId, r.case_number, String(r.case_year)
        ));
        tr.lastElementChild.appendChild(btn);
      }
      tbody.appendChild(tr);
    });
  }

  area.style.display = 'block';
  area.scrollIntoView({behavior:'smooth', block:'start'});
}

function renderCNRResult(data, cnr) {
  const area  = document.getElementById('results-area');
  const thead = document.getElementById('results-thead');
  const tbody = document.getElementById('results-tbody');
  document.getElementById('results-count').textContent = '1 result';

  thead.innerHTML = '<tr><th>CNR</th><th>Details</th></tr>';

  let content = '';
  if (data.format === 'structured') {
    content = renderStructuredHistory(data);
  } else {
    content = `<pre style="font-size:.78rem;margin:0">${esc(JSON.stringify(data, null, 2))}</pre>`;
  }

  tbody.innerHTML = `<tr>
    <td style="white-space:nowrap"><span class="badge badge-cnr">${esc(cnr)}</span></td>
    <td>${content}</td>
  </tr>`;

  area.style.display = 'block';
  area.scrollIntoView({behavior:'smooth', block:'start'});
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function showErr(el, msg) { el.textContent = msg; el.style.display = 'block'; }
function clearResults() {
  document.getElementById('results-area').style.display = 'none';
  document.getElementById('results-thead').innerHTML = '';
  document.getElementById('results-tbody').innerHTML = '';
}
function showSpinner(msg) {
  document.getElementById('spinner-msg').innerHTML = msg;
  document.getElementById('spinner').classList.add('show');
}
function hideSpinner() { document.getElementById('spinner').classList.remove('show'); }

// ── Structured history renderer ──────────────────────────────────────────────
function kv(label, value) {
  if (!value) return '';
  return `<tr><td class="text-muted" style="white-space:nowrap;width:200px;font-size:.82rem">${esc(label)}</td>
          <td style="font-size:.85rem"><strong>${esc(value)}</strong></td></tr>`;
}

function renderStructuredHistory(d) {
  let html = '';

  // Case Details
  if (d.case_details && Object.keys(d.case_details).length) {
    html += `<h6 class="fw-bold mt-2 mb-1" style="color:#1a3c5e">Case Details</h6>
      <table class="table table-sm table-bordered mb-3" style="font-size:.85rem">
        <tbody>${Object.entries(d.case_details).map(([k,v]) => kv(k,v)).join('')}</tbody>
      </table>`;
  }

  // Case Status
  if (d.case_status && Object.keys(d.case_status).length) {
    html += `<h6 class="fw-bold mt-2 mb-1" style="color:#c0392b">Case Status</h6>
      <table class="table table-sm table-bordered mb-3" style="font-size:.85rem;border-color:#e74c3c">
        <tbody>${Object.entries(d.case_status).map(([k,v]) => kv(k,v)).join('')}</tbody>
      </table>`;
  }

  // Parties
  if ((d.petitioners||[]).length || (d.respondents||[]).length) {
    html += `<div class="row mb-3">
      <div class="col-md-6">
        <h6 class="fw-bold" style="color:#1a3c5e">Petitioner &amp; Advocate</h6>
        <div class="border rounded p-2" style="font-size:.83rem">${(d.petitioners||['-']).map(p=>esc(p)).join('<br>')}</div>
      </div>
      <div class="col-md-6">
        <h6 class="fw-bold" style="color:#1a3c5e">Respondent &amp; Advocate</h6>
        <div class="border rounded p-2" style="font-size:.83rem">${(d.respondents||['-']).map(p=>esc(p)).join('<br>')}</div>
      </div>
    </div>`;
  }

  // Acts
  if ((d.acts||[]).length) {
    html += `<h6 class="fw-bold mt-1 mb-1" style="color:#1a3c5e">Acts</h6>
      <table class="table table-sm table-bordered mb-3" style="font-size:.82rem">
        <thead class="table-secondary"><tr><th>Act</th><th>Section(s)</th></tr></thead>
        <tbody>${d.acts.map(a=>`<tr><td>${esc(a.act)}</td><td>${esc(a.section)}</td></tr>`).join('')}</tbody>
      </table>`;
  }

  // Hearing History
  if ((d.hearings||[]).length) {
    html += `<h6 class="fw-bold mt-2 mb-1" style="color:#1a3c5e">History of Case Hearing</h6>
      <div class="table-responsive mb-3">
      <table class="table table-sm table-striped table-bordered result-table" style="font-size:.82rem">
        <thead><tr><th>Hearing Date</th><th>Purpose</th><th>Judge</th><th>Business On</th><th>List Type</th></tr></thead>
        <tbody>${d.hearings.map(h=>`<tr>
          <td><strong>${esc(h.hearing_date)}</strong></td>
          <td>${esc(h.purpose)}</td>
          <td style="font-size:.78rem">${esc(h.judge)}</td>
          <td style="font-size:.78rem">${esc(h.business_on||'-')}</td>
          <td style="font-size:.78rem">${esc(h.cause_list_type)}</td>
        </tr>`).join('')}</tbody>
      </table></div>`;
  }

  // Orders
  if ((d.orders||[]).length) {
    html += `<h6 class="fw-bold mt-2 mb-1" style="color:#1a3c5e">Orders</h6>
      <table class="table table-sm table-bordered mb-3" style="font-size:.82rem">
        <thead class="table-secondary"><tr><th>#</th><th>Date</th><th>Judge</th><th>Order</th></tr></thead>
        <tbody>${d.orders.map(o=>`<tr>
          <td>${esc(o.number)}</td>
          <td style="white-space:nowrap">${esc(o.date)}</td>
          <td style="font-size:.78rem">${esc(o.judge)}</td>
          <td>${o.pdf_url
            ? `<a href="${esc(o.pdf_url)}" target="_blank" class="btn btn-sm btn-outline-success py-0">
                <i class="fa fa-file-pdf me-1"></i>View PDF</a>`
            : '-'}</td>
        </tr>`).join('')}</tbody>
      </table>`;
  }

  return html || '<div class="text-muted text-center py-4">No data parsed from response.</div>';
}

// ── View case history ────────────────────────────────────────────────────────
let _historyModal = null;
async function viewHistory(cino, state_cd, court_code, case_ref, case_type_id, case_no, year) {
  document.getElementById('modal-case-ref').textContent = case_ref;
  document.getElementById('modal-body').innerHTML = `
    <div class="text-center py-5">
      <div class="spinner-border text-primary mb-3"></div>
      <div class="text-muted">Solving CAPTCHA &amp; fetching history from eCourts…</div>
    </div>`;

  if (!_historyModal) _historyModal = new bootstrap.Modal(document.getElementById('historyModal'));
  _historyModal.show();

  try {
    const res  = await fetch(`${BASE}/api/case-history`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cino, state_cd, court_code, case_type_id, case_no, year}),
    });
    let data;
    try { data = await res.json(); } catch(_) { data = {error: `Server error ${res.status}`}; }

    if (!res.ok) {
      document.getElementById('modal-body').innerHTML =
        `<div class="alert alert-danger">${esc(data.error || 'Failed to fetch history')}</div>`;
      return;
    }

    if (data.format === 'structured') {
      document.getElementById('modal-body').innerHTML = renderStructuredHistory(data);
    } else if ((data.format === 'tilde' || data.format === 'parsed') && data.hearings) {
      const rows = data.hearings.map(h => `<tr>
        <td>${esc(h.date||'-')}</td><td>${esc(h.purpose||'-')}</td>
        <td>${esc(h.judge||'-')}</td><td>${esc(h.next||'-')}</td>
      </tr>`).join('');
      document.getElementById('modal-body').innerHTML = `
        <table class="table table-sm table-striped result-table">
          <thead><tr><th>Date</th><th>Purpose</th><th>Judge</th><th>Next Date</th></tr></thead>
          <tbody>${rows || '<tr><td colspan=4 class=text-center>No records</td></tr>'}</tbody>
        </table>`;
    } else {
      document.getElementById('modal-body').innerHTML =
        `<pre style="font-size:.78rem;white-space:pre-wrap">${esc(JSON.stringify(data, null, 2))}</pre>`;
    }
  } catch(e) {
    document.getElementById('modal-body').innerHTML =
      `<div class="alert alert-danger">${esc(e.message)}</div>`;
  }
}

// Auto-load Calcutta on page load
window.addEventListener('DOMContentLoaded', () => {
  onHCChange().catch(console.error);
});
</script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ecourts_test_ui():
    return HTMLResponse(_HTML)

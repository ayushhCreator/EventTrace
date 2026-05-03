"""Full causelist parser for Calcutta High Court daily cause lists.

Fetches HTML from:
  https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{DD}{MM}{YYYY}.html

Returns structured dicts suitable for DB upsert.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ── URL ──────────────────────────────────────────────────────────────────────

def causelist_url(for_date: date) -> str:
    return (
        f"https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/"
        f"cla{for_date.strftime('%d%m%Y')}.html"
    )


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_causelist_html(for_date: date, timeout: int = 120) -> str | None:
    """Fetch causelist HTML.

    Tries urllib3 (fast, handles CHC legacy TLS) with streaming read.
    Falls back to Playwright if urllib3 fails.
    """
    url = causelist_url(for_date)
    log.info("Fetching causelist %s: %s", for_date, url)

    html = _fetch_urllib3(url, timeout)
    if html is not None:
        return html
    log.info("urllib3 failed, trying Playwright fallback")
    return _fetch_playwright(url, timeout)


def _fetch_urllib3(url: str, timeout: int) -> str | None:
    import ssl
    import urllib3
    from urllib3.util.timeout import Timeout

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    http = urllib3.PoolManager(ssl_context=ctx)
    t = Timeout(connect=15, read=timeout)
    try:
        resp = http.request(
            "GET", url,
            timeout=t,
            headers={"User-Agent": "Mozilla/5.0"},
            redirect=True,
            preload_content=False,  # stream — don't wait for full body before returning
        )
        if resp.status >= 400:
            log.info("Causelist HTTP %d", resp.status)
            resp.release_conn()
            return None
        chunks: list[bytes] = []
        for chunk in resp.stream(32768):
            chunks.append(chunk)
        resp.release_conn()
        data = b"".join(chunks)
        ct = resp.headers.get("content-type", "")
        charset = "utf-8"
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip()
        return data.decode(charset, errors="replace")
    except Exception as exc:
        log.warning("urllib3 fetch failed: %s", exc)
        return None


def _fetch_playwright(url: str, timeout: int) -> str | None:
    import asyncio
    from playwright.async_api import async_playwright

    async def _run() -> str | None:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                if resp is None or resp.status >= 400:
                    log.info("Playwright: causelist HTTP %s", resp and resp.status)
                    return None
                return await page.content()
            except Exception as exc:
                log.warning("Playwright fetch failed: %s", exc)
                return None
            finally:
                await context.close()
                await browser.close()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        log.warning("Playwright error: %s", exc)
        return None


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["br", "p", "div", "tr"]):
        tag.insert_after("\n")
    text = soup.get_text("\n")
    # Normalise Windows line endings + encoding artefacts
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("\xe2\x80\x93", "-")  # mojibake em-dash
    return text


# ── Split into per-court blocks ───────────────────────────────────────────────

_COURT_SPLIT_RE = re.compile(r"(?=(?:^|\n)COURT\s+NO[\.\s:]*\s*\d+)", re.IGNORECASE | re.MULTILINE)


def split_court_blocks(text: str) -> list[str]:
    return [b.strip() for b in _COURT_SPLIT_RE.split(text) if b.strip()]


# ── Regexes for header parsing ────────────────────────────────────────────────

_COURT_NO_RE    = re.compile(r"COURT\s+NO[\.\s:]*\s*(\S+)", re.IGNORECASE)
_JUDGE_RE       = re.compile(
    r"HON['’]?BLE\s+((?:CHIEF\s+)?(?:DR\.\s+)?JUSTICE\s+[A-Z][A-Z\s\.]+?)(?=\n|HON|$)",
    re.IGNORECASE,
)
_BENCH_RE       = re.compile(r"((?:DIVISION|SINGLE)\s+BENCH(?:\s*\([^)]+\))?)", re.IGNORECASE)
_SIDE_RE        = re.compile(r"(APPELLATE\s+SIDE|ORIGINAL\s+SIDE)", re.IGNORECASE)
_LIST_TYPE_RE   = re.compile(r"(DAILY|MONTHLY|SUPPLEMENTARY|SPECIAL)\s+CAUSELIST", re.IGNORECASE)
_DATE_RE        = re.compile(r"For\s+\w+\s+The\s+(\d+(?:st|nd|rd|th)?)\s+(\w+)\s+(\d{4})", re.IGNORECASE)
_NOT_SITTING_RE = re.compile(r"NOT\s+SITTING\s+ON\s+([\d\.]+)", re.IGNORECASE)
_VC_LINK_RE     = re.compile(r"VC\s+LINK\s*:\s*(https?://\S+)", re.IGNORECASE)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _first_group(pattern: re.Pattern[str], text: str, group: int = 1) -> str | None:
    m = pattern.search(text)
    return m.group(group).strip() if m else None


def _parse_date_from_block(block: str) -> str | None:
    m = _DATE_RE.search(block)
    if not m:
        return None
    day = re.sub(r"[^\d]", "", m.group(1))
    month_name = m.group(2).lower()
    year = m.group(3)
    month = _MONTHS.get(month_name)
    if not month:
        return None
    try:
        return date(int(year), month, int(day)).isoformat()
    except ValueError:
        return None


def _extract_jurisdiction(block: str) -> str | None:
    # Everything between last HON'BLE line and VC LINK (or end)
    judge_matches = list(_JUDGE_RE.finditer(block))
    if not judge_matches:
        return None
    start = judge_matches[-1].end()
    vc_m = _VC_LINK_RE.search(block)
    end = vc_m.start() if vc_m else len(block)
    chunk = block[start:end].strip()
    return chunk if chunk else None


def _clean(s: str | None) -> str | None:
    if s is None:
        return None
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip() or None


def parse_court_header(block: str) -> dict[str, Any]:
    clean_block = block.replace("\xa0", " ")
    judges = [_clean(m.group(1)) for m in _JUDGE_RE.finditer(clean_block) if m.group(1).strip()]
    return {
        "court_no":           _first_group(_COURT_NO_RE, clean_block),
        "bench_label":        _clean(_first_group(_BENCH_RE, clean_block, 1)),
        "side":               (_clean(_first_group(_SIDE_RE, clean_block, 0)) or "").upper() or None,
        "list_type":          _first_group(_LIST_TYPE_RE, clean_block, 1),
        "list_date":          _parse_date_from_block(clean_block),
        "judges":             judges,
        "not_sitting":        bool(_NOT_SITTING_RE.search(clean_block)),
        "vc_link":            _first_group(_VC_LINK_RE, clean_block),
        "jurisdiction_notes": _extract_jurisdiction(clean_block),
    }


# ── Case parsing ──────────────────────────────────────────────────────────────

_SERIAL_RE   = re.compile(r"^\d+$")
_CASE_REF_RE = re.compile(r"^([A-Z][A-Z\.\(\)]*(?:\([A-Z\(\)]+\))?)\s*/\s*(\d+)\s*/\s*(\d{4})\s*$")
_IA_RE       = re.compile(r"^IA\s+NO\s*:\s*([A-Z]+(?:\([A-Z]+\))?/\d+/\d{4})", re.IGNORECASE)
_SUBSEC_RE   = re.compile(r"^\(([A-Z][A-Z\s\-IX/&\.]+)\)\s*$")
# All-caps line = section header candidate
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z\s\-\(\)/&\.0-9]+$")

_CASE_TYPE_NORM: dict[str, str] = {
    "W.P.A.": "WPA", "WPA": "WPA", "WP.CT": "WP.CT",
    "W.P.(C)": "WPC", "WPC": "WPC",
    "M.A.T.": "MAT", "MAT": "MAT",
    "C.A.N.": "CAN", "CAN": "CAN",
    "C.O.":   "CO",  "CO":  "CO",
    "F.A.":   "FA",  "FA":  "FA",
    "A.P.O.": "APO", "APO": "APO",
    "C.S.":   "CS",  "CS":  "CS",
    "C.P.":   "CP",  "CP":  "CP",
}

_SECTION_TAGS: dict[str, str] = {
    "POLICE INACTION": "GROUP_IX",
    "GROUP - IX":      "GROUP_IX",
    "PIL":             "PIL",
    "PUBLIC INTEREST LITIGATION": "PIL",
    "TRIBUNAL MOTION": "TRIBUNAL",
    "TRIBUNAL HEARING": "TRIBUNAL",
    "WP.CT":           "TRIBUNAL",
    "GROUP - VI":      "GROUP_VI",
    "CONTEMPT":        "CONTEMPT",
    "REVIEW":          "REVIEW",
}

_HEARING_KEYWORDS = ["MOTION", "HEARING", "APPEAL"]


def _normalize_case_type(raw: str) -> str:
    key = raw.strip().upper().replace(" ", "")
    return _CASE_TYPE_NORM.get(key, key)


def _normalize_party(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper()
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\bAND\s+ORS\.?\b", "& ORS.", s)
    s = re.sub(r"\bAND\s+ANR\.?\b", "& ANR.", s)
    s = re.sub(r"\.{2,}", ".", s)  # collapse double dots
    return s or None


def _normalize_advocate(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().upper()
    s = re.sub(r"^(MR\.?|MRS\.?|MS\.?|DR\.?|LD\.?\s+ADV\.?|ADV\.?)\s+", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip() or None


def _classify_section(section: str | None, subsection: str | None) -> tuple[str | None, str | None]:
    s   = (section or "").upper()
    sub = (subsection or "").upper()
    category = next((v for k, v in _SECTION_TAGS.items() if k in s), section)
    h_type   = next((k for k in _HEARING_KEYWORDS if k in s or k in sub), None)
    return category, h_type


def parse_cases_from_block(block: str) -> list[dict[str, Any]]:
    """State-machine parser. Each HTML element renders on its own line."""
    # Normalise non-breaking spaces, strip each line
    lines = [ln.replace("\xa0", " ").strip() for ln in block.splitlines()]
    non_empty = [ln for ln in lines if ln]

    cases: list[dict[str, Any]] = []
    current_section: str | None = None
    current_subsection: str | None = None

    # State for current case being built
    serial: int | None = None
    case_ref: str | None = None
    case_type: str | None = None
    case_number: str | None = None
    case_year: int | None = None
    pet_parts: list[str] = []
    respondent: str | None = None
    advocate: str | None = None
    ia_numbers: list[str] = []
    pro_se = False
    raw_lines: list[str] = []
    after_vs = False
    after_respondent = False

    def _flush() -> None:
        nonlocal serial, case_ref, case_type, case_number, case_year
        nonlocal pet_parts, respondent, advocate, ia_numbers, pro_se
        nonlocal raw_lines, after_vs, after_respondent
        if serial is None or case_ref is None:
            serial = case_ref = case_type = case_number = case_year = None
            pet_parts = []
            ia_numbers = []
            raw_lines = []
            respondent = advocate = None
            pro_se = False
            after_vs = after_respondent = False
            return

        cat, h_type = _classify_section(current_section, current_subsection)
        cases.append({
            "serial_no":    serial,
            "case_ref":     case_ref,
            "case_type":    case_type,
            "case_number":  case_number,
            "case_year":    case_year,
            "petitioner":   _normalize_party(" ".join(pet_parts)) if pet_parts else None,
            "respondent":   _normalize_party(respondent),
            "advocate":     _normalize_advocate(advocate),
            "pro_se":       pro_se,
            "ia_numbers":   list(ia_numbers),
            "section":      cat,
            "subsection":   current_subsection,
            "hearing_type": h_type,
            "raw_text":     "\n".join(raw_lines),
        })
        serial = case_ref = case_type = case_number = case_year = None
        pet_parts = []
        ia_numbers = []
        raw_lines = []
        respondent = advocate = None
        pro_se = False
        after_vs = after_respondent = False

    i = 0
    while i < len(non_empty):
        line = non_empty[i]

        # IA NO — highest priority, can appear anywhere in a case
        ia_m = _IA_RE.match(line)
        if ia_m and serial is not None:
            ia_numbers.append(ia_m.group(1))
            raw_lines.append(line)
            i += 1
            continue

        # Serial number alone → start new case
        if _SERIAL_RE.match(line):
            _flush()
            serial = int(line)
            raw_lines = [line]
            i += 1
            continue

        # Section headers only appear between cases (serial is None)
        if serial is None and _ALL_CAPS_RE.match(line) and line != "VS" and len(line) < 100:
            if not _CASE_REF_RE.match(line):
                current_section = line
                current_subsection = None
                if i + 1 < len(non_empty):
                    sub_m = _SUBSEC_RE.match(non_empty[i + 1])
                    if sub_m:
                        current_subsection = sub_m.group(1).strip()
                        i += 2
                        continue
                i += 1
                continue

        if serial is None:
            i += 1
            continue

        # Case ref — first line after serial
        if case_ref is None:
            cr_m = _CASE_REF_RE.match(line)
            if cr_m:
                case_type   = _normalize_case_type(cr_m.group(1))
                case_number = cr_m.group(2).lstrip("0") or cr_m.group(2)
                case_year   = int(cr_m.group(3))
                case_ref    = f"{case_type}/{case_number}/{case_year}"
                raw_lines.append(line)
                i += 1
                continue
            # Unexpected line before case ref — skip
            i += 1
            continue

        # VS line
        if line.upper() == "VS":
            after_vs = True
            raw_lines.append(line)
            i += 1
            continue

        # Before VS: petitioner lines
        if not after_vs:
            pet_parts.append(line)
            raw_lines.append(line)
            i += 1
            continue

        # After VS: respondent then advocate
        if not after_respondent:
            respondent = line
            after_respondent = True
            raw_lines.append(line)
            i += 1
            continue

        if advocate is None:
            # Next line is advocate (could be all-caps name)
            # Only skip if it's a serial number (handled above already)
            if "PETITIONER IN PERSON" in line.upper():
                pro_se = True
            advocate = line
            raw_lines.append(line)
            i += 1
            continue

        # After advocate: only IA lines expected; anything else ends this case
        # (handled by serial detection at top of loop)
        i += 1

    _flush()
    return cases


# ── Top-level parse ───────────────────────────────────────────────────────────

def parse_causelist(html: str, for_date: date | None = None) -> list[dict[str, Any]]:
    """Parse full causelist HTML. Returns list of court dicts each with 'bench' + 'cases'."""
    text = html_to_text(html)
    blocks = split_court_blocks(text)
    results: list[dict[str, Any]] = []

    for block in blocks:
        header = parse_court_header(block)
        if header["list_date"] is None and for_date is not None:
            header["list_date"] = for_date.isoformat()
        cases = parse_cases_from_block(block)
        results.append({"bench": header, "cases": cases})

    return results


# ── DB upsert helpers ─────────────────────────────────────────────────────────

def upsert_causelist(parsed: list[dict[str, Any]], db: Any, scraped_at: datetime | None = None) -> int:
    """Write parsed causelist to DB. Delegates to db.store_causelist()."""
    return db.store_causelist(parsed, scraped_at=scraped_at)


# ── CLI entry ─────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI: chd-scrape-causelist [YYYY-MM-DD] [--store]"""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from datetime import timedelta
    from ..config import Settings

    args = sys.argv[1:]
    store = "--store" in args
    date_args = [a for a in args if a != "--store"]

    if date_args:
        for_date = date.fromisoformat(date_args[0])
    else:
        for_date = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()

    html = fetch_causelist_html(for_date)
    if not html:
        print(f"No causelist available for {for_date}")
        sys.exit(1)

    parsed = parse_causelist(html, for_date)
    total_cases = sum(len(c["cases"]) for c in parsed)
    print(f"Parsed {len(parsed)} courts, {total_cases} cases for {for_date}")

    for court in parsed:
        b = court["bench"]
        print(
            f"  Court {str(b['court_no'] or '?'):>4}  {len(court['cases']):>4} cases"
            f"  {'NOT SITTING' if b['not_sitting'] else 'sitting':12}"
            f"  judges: {', '.join(b['judges'][:2])}"
        )

    if store:
        settings = Settings()
        from ..db import get_db
        db = get_db(settings)
        db.ensure_schema()
        n = db.store_causelist(parsed)
        print(f"Stored {n} cases to DB.")

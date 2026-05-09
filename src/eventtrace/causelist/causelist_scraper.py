from __future__ import annotations

import re
from datetime import date, datetime, timezone

import structlog

from ..config import Settings
from ..db import DB
from .causelist_parser import fetch_causelist_html, html_to_text

log = structlog.get_logger()

# Matches: COURT NO. 1 ... VC LINK: https://...
# Handles "COURT NO. 1", "COURT NO.1", "COURT NO : 1" etc.
_COURT_BLOCK_RE = re.compile(
    r"COURT\s+NO[\.\s:]*\s*(\d+)(.*?)(?=COURT\s+NO[\.\s:]*\s*\d+|$)",
    re.DOTALL | re.IGNORECASE,
)
_VC_LINK_RE = re.compile(
    r"VC\s+LINK\s*:\s*(https?://\S+)",
    re.IGNORECASE,
)


def _causelist_url(for_date: date) -> str:
    dd = for_date.strftime("%d")
    mm = for_date.strftime("%m")
    yyyy = for_date.strftime("%Y")
    return f"https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{dd}{mm}{yyyy}.html"


def _extract_vc_links(text: str) -> dict[str, str]:
    """Parse plain text from cause list HTML → {room_no: zoom_url}."""
    result: dict[str, str] = {}
    for block_match in _COURT_BLOCK_RE.finditer(text):
        room_no = block_match.group(1).strip()
        block_text = block_match.group(2)
        vc_match = _VC_LINK_RE.search(block_text)
        if vc_match:
            zoom_url = vc_match.group(1).strip().rstrip(".,;)")
            if room_no in result and result[room_no] != zoom_url:
                log.warning(
                    "Court %s has conflicting VC links: %s vs %s — keeping first",
                    room_no,
                    result[room_no],
                    zoom_url,
                )
            elif room_no in result:
                log.debug("Court %s duplicated in cause list (same URL), skipping", room_no)
            else:
                result[room_no] = zoom_url
    return result


def scrape_vc_links(for_date: date, settings: Settings) -> dict[str, str]:
    """Fetch cause list HTML and extract {room_no: zoom_url}.

    This path intentionally avoids Playwright.
    The cause-list URLs are static HTML and are more reliably fetched via
    urllib3 (with legacy TLS handling) than a browser navigation.
    Returns empty dict if unavailable.
    """

    # (settings currently unused, but kept in signature for backward compatibility)
    _ = settings

    url = _causelist_url(for_date)
    html = fetch_causelist_html(for_date, timeout=120, url=url)
    if not html:
        return {}

    text = html_to_text(html)
    links = _extract_vc_links(text)
    log.info("Found %d VC links for %s: courts %s", len(links), for_date, sorted(links.keys()))
    return links


def scrape_and_store_vc_links(for_date: date, settings: Settings, db: DB) -> dict[str, str]:
    """Sync wrapper: scrape VC links and persist to DB."""
    links = scrape_vc_links(for_date, settings)
    date_str = for_date.isoformat()
    now = datetime.now(timezone.utc)
    for room_no, zoom_url in links.items():
        db.upsert_vc_zoom_link(date_str, room_no, zoom_url, now)
    return links


def main() -> None:
    """CLI entry point: chd-scrape-vc [YYYY-MM-DD]"""
    import sys

    from ..core.logging_setup import configure_logging
    configure_logging()
    from ..config import Settings

    settings = Settings()
    db = DB(settings.db_path)
    db.ensure_schema()

    if len(sys.argv) > 1:
        for_date = date.fromisoformat(sys.argv[1])
    else:
        from datetime import timedelta

        for_date = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()

    links = scrape_and_store_vc_links(for_date, settings, db)
    log.info("vc links scraped", date=str(for_date), count=len(links))
    for room_no, url in sorted(links.items(), key=lambda x: x[0].zfill(5)):
        log.info("vc link", room=room_no, url=url)

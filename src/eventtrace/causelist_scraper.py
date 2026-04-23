from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone

from playwright.async_api import async_playwright

from .config import Settings
from .db import DB

log = logging.getLogger(__name__)

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
            result[room_no] = zoom_url
    return result


async def scrape_vc_links(for_date: date, settings: Settings) -> dict[str, str]:
    """Fetch cause list HTML and extract {room_no: zoom_url}. Returns empty dict if unavailable."""
    url = _causelist_url(for_date)
    log.info("Fetching cause list for %s: %s", for_date, url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if response is None or response.status >= 400:
                log.warning("Cause list not available for %s (HTTP %s)", for_date, response and response.status)
                return {}
            # Get inner text — strips HTML tags, preserving whitespace structure
            text = await page.inner_text("body")
        except Exception as exc:
            log.warning("Failed to fetch cause list for %s: %s", for_date, exc)
            return {}
        finally:
            await context.close()
            await browser.close()

    links = _extract_vc_links(text)
    log.info("Found %d VC links for %s: courts %s", len(links), for_date, sorted(links.keys()))
    return links


def scrape_and_store_vc_links(for_date: date, settings: Settings, db: DB) -> dict[str, str]:
    """Sync wrapper: scrape VC links and persist to DB."""
    links = asyncio.run(scrape_vc_links(for_date, settings))
    date_str = for_date.isoformat()
    now = datetime.now(timezone.utc)
    for room_no, zoom_url in links.items():
        db.upsert_vc_zoom_link(date_str, room_no, zoom_url, now)
    return links


def main() -> None:
    """CLI entry point: chd-scrape-vc [YYYY-MM-DD]"""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from .config import Settings
    settings = Settings()
    db = DB(settings.db_path)
    db.ensure_schema()

    if len(sys.argv) > 1:
        for_date = date.fromisoformat(sys.argv[1])
    else:
        from datetime import timedelta
        for_date = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()

    links = scrape_and_store_vc_links(for_date, settings, db)
    print(f"Scraped {len(links)} VC links for {for_date}:")
    for room_no, url in sorted(links.items(), key=lambda x: x[0].zfill(5)):
        print(f"  Room {room_no}: {url}")

from __future__ import annotations

from pathlib import Path

import structlog
from playwright.sync_api import sync_playwright

from ..config import Settings

log = structlog.get_logger()

_CAPTCHA_TEXT = "Court hearing details will Load after CAPTCHA Validation"


def _table_has_data(page) -> bool:
    """Returns True when real court rows are visible (CAPTCHA solved)."""
    try:
        tds = page.locator("table td").all()
        for td in tds:
            txt = td.inner_text().strip()
            if txt and txt != _CAPTCHA_TEXT and txt not in ("", "Court"):
                return True
    except Exception:
        pass
    return False


def main() -> None:
    from ..core.logging_setup import configure_logging

    configure_logging()

    settings = Settings(headless=False)
    state_path = Path(settings.storage_state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(settings.url, wait_until="domcontentloaded")

            log.info("solve CAPTCHA in the browser window")
            log.info("waiting for table data after CAPTCHA…")

            # Poll until real rows appear (up to 5 minutes)
            for _ in range(300):
                page.wait_for_timeout(1000)
                if _table_has_data(page):
                    log.info("table data detected — saving session")
                    break
            else:
                log.warning("table data never appeared — saving session anyway")

            context.storage_state(path=str(state_path))
            context.close()
            browser.close()

        log.info("session saved", path=str(state_path))
        log.info("you can now run: chd-run-monitor")
    except KeyboardInterrupt:
        log.info("aborted — session not saved")

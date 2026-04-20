from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from .config import Settings

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
    settings = Settings(headless=False)
    state_path = Path(settings.storage_state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(settings.url, wait_until="domcontentloaded")

            print("Solve the CAPTCHA in the browser window.")
            print("Waiting for table data to load automatically after CAPTCHA…")

            # Poll until real rows appear (up to 5 minutes)
            for _ in range(300):
                page.wait_for_timeout(1000)
                if _table_has_data(page):
                    print("Table data detected — saving session.")
                    break
            else:
                print("WARNING: Table data never appeared. Saving session anyway.")

            context.storage_state(path=str(state_path))
            context.close()
            browser.close()

        print(f"Saved storage state to {state_path}")
        print("You can now run: chd-run-monitor")
    except KeyboardInterrupt:
        print("\nAborted — session not saved.")

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import Settings


def main() -> None:
    settings = Settings(headless=False)  # force non-headless for manual captcha
    state_path = Path(settings.storage_state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(settings.url, wait_until="domcontentloaded")

        print("Solve the CAPTCHA in the browser window, then press Enter here to save the session.")
        input()

        context.storage_state(path=str(state_path))
        context.close()
        browser.close()

    print(f"Saved storage state to {state_path}")


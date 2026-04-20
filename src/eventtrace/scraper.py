from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import async_playwright

from .config import Settings

_API_PATH = "/display_api.json"


async def scrape_table_once(settings: Settings) -> list[dict[str, Any]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.headless)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate to the main page to set the correct origin, then fetch JSON
        base_url = settings.url.rsplit("/", 1)[0]
        await page.goto(settings.url, wait_until="domcontentloaded")

        rows: list[dict[str, Any]] = await page.evaluate(
            """async (apiPath) => {
                const r = await fetch(apiPath);
                if (!r.ok) return [];
                return await r.json();
            }""",
            _API_PATH,
        )

        await context.close()
        await browser.close()
        return rows if isinstance(rows, list) else []


def scrape_table_once_sync(settings: Settings) -> list[dict[str, Any]]:
    return asyncio.run(scrape_table_once(settings))

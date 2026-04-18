from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from .config import Settings
from .normalize import normalize_header, normalize_row


async def scrape_table_once(settings: Settings) -> list[dict[str, Any]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.headless)

        context_kwargs: dict[str, Any] = {}
        storage_path = Path(settings.storage_state_path)
        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        await page.goto(settings.url, wait_until="domcontentloaded")

        await page.wait_for_selector(settings.table_selector, timeout=60_000)
        table = page.locator(settings.table_selector).first

        header_cells = table.locator("tr").first.locator("th")
        headers = [
            normalize_header(await header_cells.nth(i).inner_text())
            for i in range(await header_cells.count())
        ]

        rows: list[dict[str, Any]] = []
        tr_count = await table.locator("tr").count()
        for idx in range(1, tr_count):
            tr = table.locator("tr").nth(idx)
            td_cells = tr.locator("td")
            col_count = await td_cells.count()
            if col_count == 0:
                continue
            cols = []
            for j in range(col_count):
                cols.append((await td_cells.nth(j).inner_text()).strip())
            row_dict = dict(zip(headers, cols))
            rows.append(normalize_row(row_dict))

        await context.close()
        await browser.close()
        return rows


def scrape_table_once_sync(settings: Settings) -> list[dict[str, Any]]:
    return asyncio.run(scrape_table_once(settings))

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from .config import Settings
from .normalize import normalize_header, normalize_row


async def _pick_best_table(page, table_selector: str):
    tables = page.locator(table_selector)
    count = await tables.count()
    if count <= 1:
        return tables.first

    best_idx = 0
    best_score = (-1, -1)  # (header_count, first_row_cells)
    for idx in range(min(count, 8)):
        table = tables.nth(idx)
        header_count = await table.locator("thead tr").first.locator("th").count()
        if header_count == 0:
            header_count = await table.locator("tr").first.locator("th").count()

        body_first_row = table.locator("tbody tr").first
        first_row_cells = await body_first_row.locator("th,td").count()
        score = (header_count, first_row_cells)
        if score > best_score:
            best_score = score
            best_idx = idx

    return tables.nth(best_idx)


async def _extract_table_rows(table) -> list[dict[str, Any]]:
    header_cells = table.locator("thead tr").first.locator("th")
    header_count = await header_cells.count()
    if header_count == 0:
        header_cells = table.locator("tr").first.locator("th")
        header_count = await header_cells.count()

    headers = [
        normalize_header(await header_cells.nth(i).inner_text())
        for i in range(header_count)
    ]

    rows: list[dict[str, Any]] = []
    tbody_rows = table.locator("tbody tr")
    use_tbody = (await tbody_rows.count()) > 0
    row_locator = tbody_rows if use_tbody else table.locator("tr")
    tr_count = await row_locator.count()

    start_idx = 0
    if not use_tbody and (await table.locator("thead").count()) == 0:
        start_idx = 1

    for idx in range(start_idx, tr_count):
        tr = row_locator.nth(idx)
        cells = tr.locator("th,td")
        col_count = await cells.count()
        if col_count == 0:
            continue
        cols = []
        for j in range(col_count):
            cols.append((await cells.nth(j).inner_text()).strip())

        row_dict = dict(zip(headers, cols))
        rows.append(normalize_row(row_dict))

    return rows


async def scrape_table_once(settings: Settings) -> list[dict[str, Any]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.headless,
            chromium_sandbox=settings.chromium_sandbox,
        )

        context_kwargs: dict[str, Any] = {}
        storage_path = Path(settings.storage_state_path)
        if storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        await page.goto(settings.url, wait_until="domcontentloaded")

        await page.wait_for_selector(settings.table_selector, timeout=60_000)
        table = await _pick_best_table(page, settings.table_selector)
        rows = await _extract_table_rows(table)

        await context.close()
        await browser.close()
        return rows


def scrape_table_once_sync(settings: Settings) -> list[dict[str, Any]]:
    return asyncio.run(scrape_table_once(settings))

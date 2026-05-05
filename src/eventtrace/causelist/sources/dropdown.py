"""Dynamic dropdown-based cause list scraper (Playwright).

Handles pages with <select> dropdowns for: Date / List Type / Court Type.
Provide the base URL and dropdown selectors via config.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from .base import CauseListSource, SourceResult

log = logging.getLogger(__name__)


@dataclass
class DropdownConfig:
    """Selectors and option values for one (side, list_type) combination."""
    url: str
    side: str
    list_type: str
    source_id: str

    # CSS selectors for each dropdown
    date_selector: str = "select[name='date']"
    list_type_selector: str = "select[name='list_type']"
    court_type_selector: str = "select[name='court_type']"

    # Option value to select for court_type (e.g. "AS" or "OS")
    court_type_value: str = "AS"
    # Option value to select for list_type (e.g. "Daily" or "Supplementary")
    list_type_value: str = "Daily"

    # CSS selector that wraps the rendered HTML table after dropdown submit
    content_selector: str = "body"
    # Button/submit selector (None = selecting the dropdown auto-submits)
    submit_selector: str | None = None

    timeout_ms: int = 30_000


class DropdownSource(CauseListSource):
    """Generic Playwright scraper for dropdown-based cause list pages.

    Instantiate with a DropdownConfig for each (side, list_type) combo.
    Register multiple instances in the source registry for full coverage.

    Usage:
        config = DropdownConfig(
            url="https://calcuttahighcourt.gov.in/cause-list",
            side="ORIGINAL SIDE",
            list_type="DAILY",
            source_id="original_daily",
            court_type_value="OS",
            list_type_value="Daily",
        )
        source = DropdownSource(config)
    """

    def __init__(self, config: DropdownConfig) -> None:
        self._cfg = config
        self.source_id = config.source_id
        self.side = config.side
        self.list_type = config.list_type

    def is_enabled(self) -> bool:
        # Disabled until URL is configured (non-empty URL required)
        return bool(self._cfg.url)

    def fetch(self, for_date: date) -> SourceResult:
        try:
            courts = asyncio.run(self._async_fetch(for_date))
            return SourceResult(
                source_id=self.source_id,
                side=self.side,
                list_type=self.list_type,
                for_date=for_date,
                courts=courts,
            )
        except Exception as exc:
            log.error("[%s] fetch failed for %s: %s", self.source_id, for_date, exc)
            return SourceResult(
                source_id=self.source_id,
                side=self.side,
                list_type=self.list_type,
                for_date=for_date,
                error=str(exc),
            )

    async def _async_fetch(self, for_date: date) -> list[dict[str, Any]]:
        from playwright.async_api import async_playwright
        from ..causelist_parser import parse_causelist

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(self._cfg.url, wait_until="domcontentloaded",
                                timeout=self._cfg.timeout_ms)

                # Select court type
                await self._select_option(page, self._cfg.court_type_selector,
                                          self._cfg.court_type_value)
                # Select list type
                await self._select_option(page, self._cfg.list_type_selector,
                                          self._cfg.list_type_value)
                # Select date — try exact ISO match first, then formatted variants
                date_value = await self._select_date(page, for_date)
                if not date_value:
                    log.info("[%s] date %s not in dropdown for %s",
                             self.source_id, for_date, self._cfg.url)
                    return []

                if self._cfg.submit_selector:
                    await page.click(self._cfg.submit_selector)
                    await page.wait_for_load_state("networkidle",
                                                   timeout=self._cfg.timeout_ms)

                html = await page.inner_html(self._cfg.content_selector)
                if not html.strip():
                    return []

                courts = parse_causelist(html, for_date)
                for court in courts:
                    court["bench"].setdefault("side", self.side)
                    court["bench"].setdefault("list_type", self.list_type)
                    court["bench"]["source_id"] = self.source_id
                return courts
            finally:
                await context.close()
                await browser.close()

    async def _select_option(self, page: Any, selector: str, value: str) -> None:
        """Select by value; silently skip if selector not found."""
        try:
            await page.select_option(selector, value=value,
                                     timeout=5_000)
        except Exception:
            log.debug("[%s] selector %r not found or value %r unavailable",
                      self.source_id, selector, value)

    async def _select_date(self, page: Any, for_date: date) -> str | None:
        """Try common date formats used in court dropdowns."""
        formats = [
            for_date.isoformat(),                          # 2026-05-05
            for_date.strftime("%d/%m/%Y"),                 # 05/05/2026
            for_date.strftime("%d-%m-%Y"),                 # 05-05-2026
            for_date.strftime("%d%m%Y"),                   # 05052026
            for_date.strftime("%-d/%-m/%Y"),               # 5/5/2026
        ]
        for fmt in formats:
            try:
                await page.select_option(self._cfg.date_selector, value=fmt,
                                         timeout=2_000)
                return fmt
            except Exception:
                continue
        # Fall back: pick any option whose visible text contains the day+month
        try:
            options = await page.eval_on_selector_all(
                self._cfg.date_selector + " option",
                "els => els.map(e => ({value: e.value, text: e.textContent}))",
            )
            day_month = for_date.strftime("%d/%m") + f"/{for_date.year}"
            for opt in options:
                if day_month in (opt.get("text") or "") or day_month in (opt.get("value") or ""):
                    await page.select_option(self._cfg.date_selector,
                                             value=opt["value"], timeout=2_000)
                    return opt["value"]
        except Exception:
            pass
        return None

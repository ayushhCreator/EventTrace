"""Static-URL cause list source.

All Calcutta HC cause lists follow the same pattern:
  https://calcuttahighcourt.gov.in/downloads/old_cause_lists/{path}/{prefix}{DDMMYYYY}.html

Four combinations exist:
  Appellate Daily:   /AS/  + cla
  Original  Daily:   /OS/  + cl
  Appellate Monthly: /monthly/AS/ + cla
  Original  Monthly: /monthly/OS/ + cl
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .base import CauseListSource, SourceResult

log = structlog.get_logger()

_BASE = "https://calcuttahighcourt.gov.in/downloads/old_cause_lists"

Schedule = Literal["daily", "monthly"]


@dataclass(frozen=True)
class UrlConfig:
    path: str  # e.g. "AS" or "monthly/AS"
    prefix: str  # e.g. "cla" or "cl"
    side: str  # canonical: "APPELLATE SIDE" | "ORIGINAL SIDE"
    list_type: str  # canonical: "DAILY" | "MONTHLY"
    source_id: str
    schedule: Schedule = field(default="daily")

    def url(self, for_date: date) -> str:
        return f"{_BASE}/{self.path}/{self.prefix}{for_date.strftime('%d%m%Y')}.html"

    def should_run_for(self, target_date: date) -> bool:
        """Whether this source should even be attempted for the given target date.

        Monthly lists are only published in the first 7 days of the month.
        We don't need to know the exact court holiday calendar — we probe all
        weekdays in that window until we find the file.
        """
        if self.schedule == "monthly":
            return target_date.day <= 7
        return True


# All four known sources — import and use directly or via build_sources()
APPELLATE_DAILY = UrlConfig(
    path="AS",
    prefix="cla",
    side="APPELLATE SIDE",
    list_type="DAILY",
    source_id="appellate_daily",
)
ORIGINAL_DAILY = UrlConfig(
    path="OS",
    prefix="cl",
    side="ORIGINAL SIDE",
    list_type="DAILY",
    source_id="original_daily",
)
APPELLATE_MONTHLY = UrlConfig(
    path="monthly/AS",
    prefix="cla",
    side="APPELLATE SIDE",
    list_type="MONTHLY",
    source_id="appellate_monthly",
    schedule="monthly",
)
ORIGINAL_MONTHLY = UrlConfig(
    path="monthly/OS",
    prefix="cl",
    side="ORIGINAL SIDE",
    list_type="MONTHLY",
    source_id="original_monthly",
    schedule="monthly",
)


class StaticUrlSource(CauseListSource):
    """Fetches a static-URL cause list HTML file for a given date."""

    def __init__(self, config: UrlConfig) -> None:
        self._cfg = config
        self.source_id = config.source_id
        self.side = config.side
        self.list_type = config.list_type

    def should_run_for(self, target_date: date) -> bool:
        return self._cfg.should_run_for(target_date)

    def fetch(self, for_date: date) -> SourceResult:
        from ..causelist_parser import fetch_causelist_html, parse_causelist

        try:
            if self._cfg.schedule == "monthly":
                html, actual_date = self._probe_monthly(for_date)
            else:
                actual_date = for_date
                url = self._cfg.url(for_date)
                log.info("[%s] fetching %s", self.source_id, url)
                html = fetch_causelist_html(for_date, url=url)

            if not html:
                return SourceResult(
                    source_id=self.source_id,
                    side=self.side,
                    list_type=self.list_type,
                    for_date=for_date,
                    error="No HTML found in first-week probe"
                    if self._cfg.schedule == "monthly"
                    else f"No HTML for {self._cfg.url(for_date)}",
                )
            courts = parse_causelist(html, actual_date)
            for court in courts:
                # URL path (/AS/ vs /OS/) is the authoritative source of truth.
                # The HTML body rarely contains "APPELLATE SIDE" / "ORIGINAL SIDE"
                # text, so the parser returns None for those fields. Force-set
                # them here regardless of what the HTML parser found.
                court["bench"]["side"] = self.side
                court["bench"]["list_type"] = self.list_type
                court["bench"]["source_id"] = self.source_id
            return SourceResult(
                source_id=self.source_id,
                side=self.side,
                list_type=self.list_type,
                for_date=actual_date,
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

    def _probe_monthly(self, for_date: date) -> tuple[str | None, date]:
        """Try weekdays in days 1–7 of for_date's month to find the published file.

        The court publishes the monthly list on the first court working day,
        which may differ from the first weekday due to public holidays.
        Returns (html, actual_date) for the first successful fetch.
        """
        from ..causelist_parser import fetch_causelist_html

        year, month = for_date.year, for_date.month
        for day in range(1, 8):
            try:
                candidate = date(year, month, day)
            except ValueError:
                break
            if candidate.weekday() >= 5:  # skip weekends
                continue
            url = self._cfg.url(candidate)
            log.info("[%s] probing monthly %s", self.source_id, url)
            html = fetch_causelist_html(candidate, url=url)
            if html:
                log.info("[%s] found monthly list at %s", self.source_id, candidate)
                return html, candidate
        return None, for_date

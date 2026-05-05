"""Appellate Side daily cause list — static HTML files published by the court.

URL pattern: https://calcuttahighcourt.gov.in/downloads/old_cause_lists/AS/cla{DD}{MM}{YYYY}.html
Court publishes the *next working day's* list each evening.
"""

from __future__ import annotations

import logging
from datetime import date

from .base import CauseListSource, SourceResult

log = logging.getLogger(__name__)


class AppellateStaticSource(CauseListSource):
    source_id = "appellate_static"
    side = "APPELLATE SIDE"
    list_type = "DAILY"

    def fetch(self, for_date: date) -> SourceResult:
        from ..causelist_parser import fetch_causelist_html, parse_causelist

        try:
            html = fetch_causelist_html(for_date)
            if not html:
                return SourceResult(
                    source_id=self.source_id,
                    side=self.side,
                    list_type=self.list_type,
                    for_date=for_date,
                    error=f"No HTML for {for_date}",
                )
            courts = parse_causelist(html, for_date)
            # Stamp side/list_type on every bench (parser may already set these)
            for court in courts:
                court["bench"].setdefault("side", self.side)
                court["bench"].setdefault("list_type", self.list_type)
                court["bench"]["source_id"] = self.source_id
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

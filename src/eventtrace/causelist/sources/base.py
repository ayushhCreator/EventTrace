"""Abstract base for all cause list sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class SourceResult:
    source_id: str          # e.g. "appellate_static", "original_dropdown"
    side: str               # "APPELLATE SIDE" | "ORIGINAL SIDE"
    list_type: str          # "DAILY" | "MONTHLY" | "SUPPLEMENTARY" | ...
    for_date: date
    courts: list[dict[str, Any]] = field(default_factory=list)  # parse_causelist() output
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.courts)

    @property
    def total_cases(self) -> int:
        return sum(len(c["cases"]) for c in self.courts)


class CauseListSource(ABC):
    """One (side, list_type) combination from one website."""

    source_id: str
    side: str
    list_type: str

    @abstractmethod
    def fetch(self, for_date: date) -> SourceResult:
        """Fetch, parse, return SourceResult. Never raises — captures errors."""
        ...

    def is_enabled(self) -> bool:
        """Override to disable a source without removing it from the registry."""
        return True

    def should_run_for(self, target_date: date) -> bool:
        """Override to skip this source on dates it can't have data.

        Default: always run. Monthly sources override to only run on the
        first working day of each month.
        """
        return True

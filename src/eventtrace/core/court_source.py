"""CourtSource Protocol — defines the interface every court scraper must implement.

Open/Closed principle: the scraper runner accepts CourtSource and never needs
to know which court it is. To add a new court, implement this Protocol;
no existing code changes.

Interface Segregation: only the methods a scraper runner actually needs.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable


@runtime_checkable
class CourtSource(Protocol):
    """Abstract scraper interface for one High Court.

    court_id:   3-letter canonical code  (e.g. "CHD", "DEL", "BOM")
    domain:     FQDN of court website    (e.g. "calcuttahighcourt.gov.in")
    """

    court_id: str
    domain: str

    def url_for_date(self, d: date) -> str:
        """Return the primary causelist URL for the given date."""
        ...

    def parse(self, html: str, d: date) -> list[dict]:
        """Parse causelist HTML/text and return list of entry dicts.

        Each dict must include at minimum:
          case_number, serial_number, court_id, bench_id,
          judge_name, petitioner, respondent, hearing_date
        """
        ...


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, CourtSource] = {}


def register(source: CourtSource) -> None:
    """Register a CourtSource implementation by its court_id."""
    _REGISTRY[source.court_id] = source


def get_source(court_id: str) -> CourtSource | None:
    """Return registered CourtSource for court_id, or None."""
    return _REGISTRY.get(court_id)


def all_sources() -> list[CourtSource]:
    return list(_REGISTRY.values())

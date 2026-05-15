"""Source registry — one place to add/remove cause list sources.

Add a new source here and the scheduler picks it up automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .sources.static_url import (
    StaticUrlSource,
    APPELLATE_DAILY,
    ORIGINAL_DAILY,
    APPELLATE_MONTHLY,
    ORIGINAL_MONTHLY,
    APPELLATE_SUPP_1, APPELLATE_SUPP_2, APPELLATE_SUPP_3, APPELLATE_SUPP_4, APPELLATE_SUPP_5,
    ORIGINAL_SUPP_1,  ORIGINAL_SUPP_2,  ORIGINAL_SUPP_3,  ORIGINAL_SUPP_4,  ORIGINAL_SUPP_5,
    APPELLATE_LOK_ADALAT,
    ORIGINAL_LOK_ADALAT,
)

if TYPE_CHECKING:
    from .sources.base import CauseListSource


def build_sources() -> list[CauseListSource]:
    """Return all enabled cause list sources.

    Order matters: daily sources first (highest priority), then supplementary
    (published ad-hoc, checked every evening window), then monthly/lok_adalat.
    To disable a source temporarily, comment it out here.
    """
    return [
        # Core daily lists
        StaticUrlSource(APPELLATE_DAILY),
        StaticUrlSource(ORIGINAL_DAILY),
        # Supplementary lists (AS + OS, slots 1-5 each)
        StaticUrlSource(APPELLATE_SUPP_1),
        StaticUrlSource(APPELLATE_SUPP_2),
        StaticUrlSource(APPELLATE_SUPP_3),
        StaticUrlSource(APPELLATE_SUPP_4),
        StaticUrlSource(APPELLATE_SUPP_5),
        StaticUrlSource(ORIGINAL_SUPP_1),
        StaticUrlSource(ORIGINAL_SUPP_2),
        StaticUrlSource(ORIGINAL_SUPP_3),
        StaticUrlSource(ORIGINAL_SUPP_4),
        StaticUrlSource(ORIGINAL_SUPP_5),
        # Lok Adalat (ad-hoc dates)
        StaticUrlSource(APPELLATE_LOK_ADALAT),
        StaticUrlSource(ORIGINAL_LOK_ADALAT),
        # Monthly lists (first-week probe only)
        StaticUrlSource(APPELLATE_MONTHLY),
        StaticUrlSource(ORIGINAL_MONTHLY),
    ]

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
)

if TYPE_CHECKING:
    from .sources.base import CauseListSource


def build_sources() -> list[CauseListSource]:
    """Return all enabled cause list sources.

    Order matters: earlier sources are attempted first within each retry window.
    To disable a source temporarily, comment it out here.
    """
    return [
        StaticUrlSource(APPELLATE_DAILY),
        StaticUrlSource(ORIGINAL_DAILY),
        StaticUrlSource(APPELLATE_MONTHLY),
        StaticUrlSource(ORIGINAL_MONTHLY),
    ]

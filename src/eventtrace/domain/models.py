from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EventTrace:
    court_id: str
    field_name: str
    old_value: str | None
    new_value: str | None
    start_time: datetime
    end_time: datetime

    @property
    def duration_seconds(self) -> int:
        return max(0, int((self.end_time - self.start_time).total_seconds()))


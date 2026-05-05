from __future__ import annotations

import re
from datetime import datetime, timezone


DATE_YYYY_MM_DD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_yyyy_mm_dd(value: str, *, field_name: str) -> str:
    if not DATE_YYYY_MM_DD_RE.match(value):
        raise ValueError(f"{field_name} must be YYYY-MM-DD")
    return value


def ensure_utc_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def parse_dt_maybe_iso(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc_aware(value)
    return ensure_utc_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))

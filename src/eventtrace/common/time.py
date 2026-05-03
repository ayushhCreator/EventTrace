from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    # Python 3.11+ supports Z; keep general for callers.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    return datetime.now(IST)


def ist_today_date() -> date:
    return ist_now().date()


def ist_today_str() -> str:
    return ist_now().strftime("%Y-%m-%d")

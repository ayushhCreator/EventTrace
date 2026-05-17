"""Redis-based notification deduplication.

Key: notif:dedup:{dedup_key}   TTL: 24h (configurable per call)
Fail-open: when Redis unavailable, always returns not-duplicate so
notifications still go through (better noisy than silent).

SOLID: Single Responsibility — only deduplication, nothing else.
DRY: one place to change key prefix or TTL logic.
"""

from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

_KEY_PREFIX = "notif:dedup:"
_DEFAULT_TTL_HOURS = 24


def is_duplicate(redis_client: Any, dedup_key: str, ttl_hours: int = _DEFAULT_TTL_HOURS) -> bool:
    """Return True if this notification was already sent (key exists in Redis).

    Fail-open: returns False (not duplicate) when Redis is unavailable.
    """
    if redis_client is None:
        return False
    key = _KEY_PREFIX + dedup_key
    try:
        return bool(redis_client.exists(key))
    except Exception as exc:
        log.warning("notif_dedup.is_duplicate failed", exc=str(exc))
        return False


def mark_sent(redis_client: Any, dedup_key: str, ttl_hours: int = _DEFAULT_TTL_HOURS) -> None:
    """Set the dedup key with TTL so future sends are blocked for ttl_hours."""
    if redis_client is None:
        return
    key = _KEY_PREFIX + dedup_key
    try:
        redis_client.setex(key, ttl_hours * 3600, 1)
    except Exception as exc:
        log.warning("notif_dedup.mark_sent failed", exc=str(exc))


def clear(redis_client: Any, dedup_key: str) -> None:
    """Remove a dedup key (use when re-sending is explicitly required)."""
    if redis_client is None:
        return
    key = _KEY_PREFIX + dedup_key
    try:
        redis_client.delete(key)
    except Exception as exc:
        log.warning("notif_dedup.clear failed", exc=str(exc))

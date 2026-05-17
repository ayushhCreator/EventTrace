"""Redis client singleton.

Returns None gracefully when REDIS_URL is not set (dev/SQLite mode).
All callers must handle None — never crash on missing Redis.
"""

from __future__ import annotations

import os
from typing import Optional

import structlog

log = structlog.get_logger()

_client: Optional["redis.Redis"] = None  # type: ignore[name-defined]
_initialized = False


def get_redis() -> Optional["redis.Redis"]:  # type: ignore[name-defined]
    """Return Redis client, or None if REDIS_URL is not configured."""
    global _client, _initialized
    if _initialized:
        return _client

    _initialized = True
    url = os.getenv("REDIS_URL", "")
    if not url:
        log.info("redis.disabled", reason="REDIS_URL not set")
        return None

    try:
        import redis  # type: ignore[import]
        _client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _client.ping()
        log.info("redis.connected", url=url.split("@")[-1])
    except Exception as exc:
        log.warning("redis.connect_failed", error=str(exc))
        _client = None

    return _client


def reset_redis_client() -> None:
    """Force re-initialization (for tests)."""
    global _client, _initialized
    _client = None
    _initialized = False

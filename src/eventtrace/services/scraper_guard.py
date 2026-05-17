"""Scraper request discipline guard.

Enforces per-domain rate limits and 429-backoff via Redis.

Usage:
    from services.scraper_guard import ScraperGuard
    guard = ScraperGuard(redis_client)
    if not guard.acquire(domain):
        time.sleep(5)  # wait and retry
    resp = http.get(url)
    if resp.status_code == 429:
        guard.record_429(domain, db)
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from .admin_alerts import create_admin_alert

log = structlog.get_logger()

_DOMAIN_TTL_SECONDS = 5        # 1 request per 5s per domain
_BACKOFF_SECONDS = 60          # wait on 429
_MAX_CONSECUTIVE_429S = 3      # alert threshold
_429_COUNT_TTL = 300           # 5-min window for consecutive 429 counter


class ScraperGuard:
    """Thread-safe per-domain rate limiter backed by Redis.

    Falls back gracefully when Redis is unavailable (no rate limiting).
    """

    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    def acquire(self, domain: str) -> bool:
        """Return True if the request is allowed now.

        Sets Redis key `ratelimit:scraper:{domain}` with DOMAIN_TTL_SECONDS TTL
        if not already set (SET NX EX). If key already exists → rate limited → return False.
        """
        if self._r is None:
            return True  # no Redis → no enforcement
        key = f"ratelimit:scraper:{domain}"
        try:
            result = self._r.set(key, 1, nx=True, ex=_DOMAIN_TTL_SECONDS)
            return result is not None
        except Exception as exc:
            log.warning("scraper_guard.acquire failed", exc=str(exc))
            return True  # fail open

    def wait_for_slot(self, domain: str, poll_interval: float = 0.5) -> None:
        """Block until acquire() returns True (busy-wait with sleep)."""
        while not self.acquire(domain):
            time.sleep(poll_interval)

    def record_429(self, domain: str, db: Any) -> int:
        """Increment consecutive-429 counter for domain.

        Returns the new count. When count reaches MAX_CONSECUTIVE_429S,
        fires an admin alert and returns the count.
        """
        count = 1
        if self._r is not None:
            count_key = f"scraper:429_count:{domain}"
            try:
                count = self._r.incr(count_key)
                if count == 1:
                    self._r.expire(count_key, _429_COUNT_TTL)
            except Exception as exc:
                log.warning("scraper_guard.record_429 redis failed", exc=str(exc))

        log.warning("scraper: HTTP 429 received", domain=domain, consecutive_count=count)

        if count >= _MAX_CONSECUTIVE_429S:
            msg = (
                f"Scraper blocked by {domain} — {count} consecutive 429s.\n"
                f"Scraping for this domain has been paused. Manual intervention may be needed."
            )
            create_admin_alert(
                db,
                alert_type="SCRAPER_BANNED",
                message=msg,
                severity="ERROR",
                metadata={"domain": domain, "consecutive_429s": count},
            )

        return count

    def reset_429_count(self, domain: str) -> None:
        """Reset counter after a successful request (domain recovered)."""
        if self._r is None:
            return
        try:
            self._r.delete(f"scraper:429_count:{domain}")
        except Exception:
            pass

    def backoff_429(self, domain: str, db: Any) -> None:
        """Record 429 then sleep BACKOFF_SECONDS."""
        self.record_429(domain, db)
        log.info("scraper: backing off", domain=domain, seconds=_BACKOFF_SECONDS)
        time.sleep(_BACKOFF_SECONDS)

    def is_banned(self, domain: str) -> bool:
        """True if domain has >= MAX_CONSECUTIVE_429S recent 429s."""
        if self._r is None:
            return False
        count_key = f"scraper:429_count:{domain}"
        try:
            val = self._r.get(count_key)
            return val is not None and int(val) >= _MAX_CONSECUTIVE_429S
        except Exception:
            return False

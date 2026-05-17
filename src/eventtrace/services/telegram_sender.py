"""Telegram Bot sender with Redis token-bucket rate limiting and DLQ.

Rate limits (Telegram Bot API limits):
  Global:    29 messages / second
  Per chat:   1 message  / second

DLQ: failed jobs (after 3 retries) are pushed to Redis list `dlq:notifications`.

SOLID:
  - Single Responsibility: only Telegram sending logic lives here.
  - Dependency Inversion: redis_client and bot_token injected, not fetched internally.
DRY: _check_rate_limit encapsulates all bucket logic in one place.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_TELEGRAM_API = "https://api.telegram.org"
_GLOBAL_LIMIT = 29       # msgs/sec across all chats
_CHAT_LIMIT = 1          # msgs/sec per chat_id
_HTTP_TIMEOUT = 5.0
_MAX_RETRIES = 3
_RETRY_DELAY = 30.0      # seconds between retries on failure
_DLQ_KEY = "dlq:notifications"


class TelegramSender:
    """Send Telegram messages with Redis token-bucket rate limiting.

    Pass redis_client=None to run without rate limiting (dev/test mode).
    """

    def __init__(self, redis_client: Any, bot_token: str) -> None:
        self._r = redis_client
        self._token = bot_token

    # ── Public API ────────────────────────────────────────────────────────────

    def send(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict]] | None = None,
    ) -> bool:
        """Send a message. Rate-limits, retries 3×, then enqueues DLQ on failure.

        Returns True if sent successfully, False if pushed to DLQ.
        """
        chat_id = str(chat_id)
        for attempt in range(1, _MAX_RETRIES + 2):
            if not self._check_rate_limit(chat_id):
                log.warning("telegram_sender: rate limited", chat_id=chat_id, attempt=attempt)
                time.sleep(1)
                continue

            ok, permanent_fail = self._do_send(chat_id, text, parse_mode, inline_keyboard)
            if ok:
                return True
            if permanent_fail:
                break

            if attempt <= _MAX_RETRIES:
                log.warning("telegram_sender: retry", chat_id=chat_id, attempt=attempt, delay=_RETRY_DELAY)
                time.sleep(_RETRY_DELAY)

        self.enqueue_dlq({
            "id": str(uuid.uuid4()),
            "channel": "telegram",
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "inline_keyboard": inline_keyboard,
        })
        return False

    def enqueue_dlq(self, job: dict) -> None:
        """Push a failed notification job to dlq:notifications Redis list."""
        if self._r is None:
            log.error("telegram_sender: DLQ unavailable (no Redis), notification lost", job=job)
            return
        try:
            self._r.rpush(_DLQ_KEY, json.dumps(job))
            log.warning("telegram_sender: pushed to DLQ", chat_id=job.get("chat_id"))
        except Exception as exc:
            log.error("telegram_sender: DLQ push failed", exc=str(exc))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_rate_limit(self, chat_id: str) -> bool:
        """Return True if allowed by token bucket. Fail-open when Redis absent."""
        if self._r is None:
            return True
        try:
            pipe = self._r.pipeline()
            global_key = "ratelimit:telegram:global"
            chat_key = f"ratelimit:telegram:chat:{chat_id}"

            pipe.incr(global_key)
            pipe.expire(global_key, 1)
            pipe.incr(chat_key)
            pipe.expire(chat_key, 1)

            results = pipe.execute()
            global_count = results[0]
            chat_count = results[2]
            return global_count <= _GLOBAL_LIMIT and chat_count <= _CHAT_LIMIT
        except Exception as exc:
            log.warning("telegram_sender: rate limit check failed", exc=str(exc))
            return True  # fail open

    def _do_send(
        self,
        chat_id: str,
        text: str,
        parse_mode: str,
        inline_keyboard: list[list[dict]] | None,
    ) -> tuple[bool, bool]:
        """Make one HTTP call to Telegram sendMessage.

        Returns (success, permanent_failure).
        permanent_failure=True means retrying is pointless (e.g. 403 bot blocked).
        """
        payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

        try:
            resp = httpx.post(
                f"{_TELEGRAM_API}/bot{self._token}/sendMessage",
                json=payload,
                timeout=_HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                return True, False
            if resp.status_code in (400, 403):
                log.warning("telegram_sender: permanent fail", status=resp.status_code, body=resp.text[:200])
                return False, True
            log.warning("telegram_sender: transient fail", status=resp.status_code, body=resp.text[:200])
            return False, False
        except Exception as exc:
            log.warning("telegram_sender: http exception", exc=str(exc))
            return False, False


# ── Module-level convenience for callers that don't own a TelegramSender ──────


def get_sender(redis_client: Any | None = None) -> TelegramSender | None:
    """Return a TelegramSender if TELEGRAM_BOT_TOKEN is configured, else None."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None
    return TelegramSender(redis_client=redis_client, bot_token=token)

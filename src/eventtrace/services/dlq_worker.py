"""Dead Letter Queue worker — drains dlq:notifications and retries failed sends.

Runs as a daemon thread inside run_monitor.py alongside the existing
notification_retry_worker. Processes Telegram failures specifically
(email failures are handled synchronously by notification_retry_worker).

Design:
  - LPOP up to _BATCH_SIZE items per cycle from dlq:notifications
  - Try to send each; on success remove from DLQ (already popped)
  - On failure: drop after _MAX_DLQ_ATTEMPTS to prevent infinite loop
  - Tracks attempt count in job payload

SOLID: Single Responsibility — only DLQ drain, not primary send path.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import structlog

from .telegram_sender import TelegramSender

log = structlog.get_logger()

_DLQ_KEY = "dlq:notifications"
_BATCH_SIZE = 10
_MAX_DLQ_ATTEMPTS = 3
_POLL_INTERVAL = 30  # seconds


def process_dlq_batch(redis_client: Any, telegram_sender: TelegramSender | None) -> int:
    """Pop up to BATCH_SIZE items and retry sending.

    Returns number of items processed (sent + permanently failed).
    Pure function — no threading, easy to test.
    """
    if redis_client is None:
        return 0

    processed = 0
    for _ in range(_BATCH_SIZE):
        raw = None
        try:
            raw = redis_client.lpop(_DLQ_KEY)
        except Exception as exc:
            log.warning("dlq_worker: redis lpop failed", exc=str(exc))
            break

        if raw is None:
            break  # DLQ empty

        try:
            job = json.loads(raw)
        except Exception:
            log.warning("dlq_worker: invalid job JSON", raw=str(raw)[:200])
            processed += 1
            continue

        attempts = job.get("dlq_attempts", 0) + 1
        job["dlq_attempts"] = attempts

        if attempts > _MAX_DLQ_ATTEMPTS:
            log.error("dlq_worker: job exceeded max attempts, dropping", job_id=job.get("id"), channel=job.get("channel"))
            processed += 1
            continue

        channel = job.get("channel", "telegram")
        sent = False

        if channel == "telegram" and telegram_sender is not None:
            chat_id = job.get("chat_id", "")
            text = job.get("text", "")
            parse_mode = job.get("parse_mode", "HTML")
            inline_keyboard = job.get("inline_keyboard")
            if chat_id and text:
                # Direct send (bypass DLQ re-enqueue inside TelegramSender)
                ok, permanent = telegram_sender._do_send(chat_id, text, parse_mode, inline_keyboard)
                sent = ok
                if permanent:
                    log.warning("dlq_worker: permanent failure, dropping", chat_id=chat_id)
                    processed += 1
                    continue

        if not sent:
            log.warning("dlq_worker: retry failed, re-enqueueing", attempts=attempts, job_id=job.get("id"))
            try:
                redis_client.rpush(_DLQ_KEY, json.dumps(job))
            except Exception as exc:
                log.error("dlq_worker: re-enqueue failed", exc=str(exc))
        else:
            log.info("dlq_worker: job sent", job_id=job.get("id"), channel=channel)

        processed += 1

    return processed


def run_dlq_worker(
    redis_client: Any,
    telegram_sender: TelegramSender | None,
    stop_event: threading.Event,
    interval: int = _POLL_INTERVAL,
) -> None:
    """Blocking loop — meant to run in a daemon thread.

    stop_event.set() to shut down gracefully.
    """
    log.info("dlq_worker: started", interval=interval)
    while not stop_event.is_set():
        try:
            n = process_dlq_batch(redis_client, telegram_sender)
            if n:
                log.info("dlq_worker: batch done", processed=n)
        except Exception as exc:
            log.error("dlq_worker: unhandled error", exc=str(exc))
        stop_event.wait(interval)
    log.info("dlq_worker: stopped")

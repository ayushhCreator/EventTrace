"""Admin alert system — insert AdminAlert row + Telegram push to admin chat.

Single Responsibility: one function creates an alert (DB + Telegram).
Dependency Inversion: accepts db: Any — works with any DB backend.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_TELEGRAM_API = "https://api.telegram.org"
_HTTP_TIMEOUT = 5.0
_MAX_RETRIES = 2
_RETRY_DELAY = 1.0

_SEVERITY_EMOJI: dict[str, str] = {
    "WARNING": "⚠️",
    "ERROR": "🔴",
    "CRITICAL": "🚨",
}


def _bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def _admin_chat_id() -> str:
    return os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")


def _send_telegram(message: str) -> bool:
    """Send message to admin chat. Retries up to _MAX_RETRIES on transient failure."""
    token = _bot_token()
    chat_id = _admin_chat_id()
    if not token or not chat_id:
        log.warning("admin_alert: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID not set")
        return False

    url = f"{_TELEGRAM_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            resp = httpx.post(url, json=payload, timeout=_HTTP_TIMEOUT)
            if resp.status_code == 200:
                return True
            log.warning(
                "admin_alert: telegram send failed",
                status=resp.status_code,
                attempt=attempt,
                body=resp.text[:200],
            )
        except Exception as exc:
            log.warning("admin_alert: telegram exception", exc=str(exc), attempt=attempt)

        if attempt <= _MAX_RETRIES:
            time.sleep(_RETRY_DELAY * attempt)

    return False


def create_admin_alert(
    db: Any,
    alert_type: str,
    message: str,
    severity: str = "WARNING",
    metadata: dict | None = None,
    source_court: str | None = None,
) -> str:
    """Insert AdminAlert into DB and push Telegram message to admin.

    Returns the new alert ID.
    severity: WARNING | ERROR | CRITICAL
    source_court: 3-letter court code (e.g. "CHD"), or None for system-wide alerts.
    """
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        db.create_admin_alert(
            id=alert_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            metadata_json=json.dumps(metadata or {}),
            source_court=source_court,
            created_at=now,
        )
        log.info(
            "admin_alert created",
            id=alert_id,
            alert_type=alert_type,
            severity=severity,
            source_court=source_court,
        )
    except Exception as exc:
        log.error("admin_alert: db insert failed", exc=str(exc))

    emoji = _SEVERITY_EMOJI.get(severity, "⚠️")
    court_tag = f" [{source_court}]" if source_court else ""
    telegram_text = f"{emoji} <b>[{severity}]{court_tag} {alert_type}</b>\n{message}"
    _send_telegram(telegram_text)

    return alert_id

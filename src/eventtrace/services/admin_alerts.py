"""Admin alert system — insert AdminAlert row + Telegram push to admin chat."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_TELEGRAM_API = "https://api.telegram.org"
_HTTP_TIMEOUT = 5.0


def _bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def _admin_chat_id() -> str:
    return os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")


def _send_telegram(message: str) -> bool:
    token = _bot_token()
    chat_id = _admin_chat_id()
    if not token or not chat_id:
        log.warning("admin_alert: TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID not set")
        return False
    try:
        resp = httpx.post(
            f"{_TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            log.warning("admin_alert: telegram send failed", status=resp.status_code, body=resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("admin_alert: telegram send exception", exc=str(exc))
        return False


def create_admin_alert(
    db: Any,
    alert_type: str,
    message: str,
    severity: str = "WARNING",
    metadata: dict | None = None,
) -> str:
    """Insert AdminAlert into DB and push Telegram message to admin.

    Returns the new alert ID.
    severity: WARNING | ERROR | CRITICAL
    """
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    import json

    try:
        db.create_admin_alert(
            id=alert_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            metadata_json=json.dumps(metadata or {}),
            created_at=now,
        )
        log.info("admin_alert created", id=alert_id, alert_type=alert_type, severity=severity)
    except Exception as exc:
        log.error("admin_alert: db insert failed", exc=str(exc))

    emoji = {"WARNING": "⚠️", "ERROR": "🔴", "CRITICAL": "🚨"}.get(severity, "⚠️")
    telegram_text = f"{emoji} <b>[{severity}] {alert_type}</b>\n{message}"
    _send_telegram(telegram_text)

    return alert_id

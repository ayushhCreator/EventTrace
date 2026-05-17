"""Notification retry worker.

Runs as a background daemon thread inside run_monitor.py.
Every 10 seconds: claim queued notifications → send → ack.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog

from .notifications import (
    _send_wati,
    _send_msg91_whatsapp,
    _wati_key,
    _msg91_whatsapp_key,
    send_email_alert,
    _email_subject,
    build_email_html,
)

log = structlog.get_logger()

_WORKER_ID = str(uuid.uuid4())[:8]
_POLL_INTERVAL = 10  # seconds
_BATCH_SIZE = 20
_LOCK_SECONDS = 90


def _dispatch_queue_item(db: Any, item: dict) -> bool:
    """Send one queued notification. Returns True on success."""
    user_id = item["user_id"]
    channel = item["channel"]
    notification_log_id = item.get("notification_log_id")
    queue_id = item["id"]

    try:
        payload = json.loads(item["payload_json"])
    except Exception:
        payload = {}

    user = db.get_user_by_id(user_id)
    if not user:
        log.warning("retry_worker: user not found", user_id=user_id, queue_id=queue_id)
        return False

    # Reconstruct message from log row or payload
    message = payload.get("message_text", "")
    if not message and notification_log_id:
        try:
            items, _ = db.get_user_notifications(user_id, limit=1, offset=0)
            for n in items:
                if n["id"] == notification_log_id:
                    message = n.get("message_text", "")
                    break
        except Exception:
            pass
    if not message:
        from .notification_dispatch import build_message
        message = build_message(payload.get("trigger_type", ""), payload)

    sent = False
    provider_response = None

    if channel == "whatsapp":
        wa_number = user.get("whatsapp_number") or user.get("phone", "")
        if not wa_number:
            log.warning("retry_worker: no WhatsApp number", user_id=user_id)
            return False

        wk = _wati_key()
        if wk:
            sent = _send_wati(wa_number, message, wk)
            provider_response = json.dumps({"sent": sent})

        if not sent:
            mk = _msg91_whatsapp_key()
            if mk:
                sent = _send_msg91_whatsapp(wa_number, message, mk)
                provider_response = json.dumps({"sent": sent})

        if not sent and not wk and not _msg91_whatsapp_key():
            log.info("retry_worker: no WA provider configured — marking sent (dev)", user_id=user_id)
            sent = True

    elif channel == "telegram":
        import os
        from ..core.redis_client import get_redis
        from .telegram_sender import TelegramSender

        chat_id = user.get("telegram_chat_id")
        if not chat_id:
            log.warning("retry_worker: no telegram_chat_id", user_id=user_id)
            return False
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            log.warning("retry_worker: TELEGRAM_BOT_TOKEN not set")
            return False
        sender = TelegramSender(redis_client=get_redis(), bot_token=token)
        sent = sender.send(str(chat_id), message, parse_mode="HTML")
        provider_response = json.dumps({"sent": sent, "provider": "telegram", "chat_id": str(chat_id)})

    elif channel == "email":
        email = user.get("email", "")
        if not email or not user.get("email_verified"):
            return False
        trigger_type = payload.get("trigger_type", "")
        case_ref = payload.get("case_ref", "")
        subject = _email_subject(trigger_type, payload, case_ref)
        unsubscribe_token = user.get("unsubscribe_token", "")
        import os as _os
        api_url = _os.getenv("CHD_PUBLIC_URL", "").rstrip("/")
        unsubscribe_url = f"{api_url}/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else ""
        body_html = build_email_html(trigger_type, payload, case_ref, unsubscribe_url=unsubscribe_url)
        body_text = payload.get("message_text", message)
        sent = send_email_alert(email, subject, body_html, body_text=body_text, db=db, user_id=user_id)
        provider_response = json.dumps({"sent": sent, "provider": "resend"})

    # Update log status
    if notification_log_id:
        try:
            from ..common.time import iso, utc_now
            status = "sent" if sent else "failed"
            db.update_notification_status(
                notification_log_id,
                status,
                provider_response=provider_response,
                delivered_at=iso(utc_now()) if sent else None,
            )
        except Exception as exc:
            log.warning("retry_worker: update_notification_status failed", exc=str(exc))

    return sent


def run_retry_worker(db: Any) -> None:
    """Main loop — intended to run in a daemon thread."""
    log.info("notification_retry_worker started", worker_id=_WORKER_ID)
    while True:
        try:
            items = db.claim_queued_notifications(
                worker_id=_WORKER_ID,
                batch_size=_BATCH_SIZE,
                lock_seconds=_LOCK_SECONDS,
            )
            for item in items:
                queue_id = item["id"]
                try:
                    success = _dispatch_queue_item(db, item)
                    db.ack_queue_item(queue_id, success=success)
                except Exception as exc:
                    log.warning("retry_worker: item dispatch error", queue_id=queue_id, exc=str(exc))
                    try:
                        db.ack_queue_item(queue_id, success=False)
                    except Exception:
                        pass
        except Exception as exc:
            log.warning("retry_worker: claim loop error", exc=str(exc))

        time.sleep(_POLL_INTERVAL)

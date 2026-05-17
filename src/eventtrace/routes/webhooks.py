from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse

log = structlog.get_logger()

from ..common.time import iso, utc_now
from ..services.deps import get_db, get_settings
from ..services.twilio import verify_twilio_signature

router = APIRouter()


@router.post("/webhook/whatsapp", response_class=HTMLResponse)
async def whatsapp_webhook(
    request: Request,
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> HTMLResponse:
    """Twilio calls this with form-encoded data for every inbound WhatsApp message."""
    from ..bots.whatsapp_bot import handle_inbound

    form = await request.form()
    form_dict = dict(form)

    if settings.twilio_auth_token:
        sig = request.headers.get("X-Twilio-Signature", "")
        public_base = os.getenv("CHD_PUBLIC_URL", "").rstrip("/")
        url = (public_base + str(request.url.path)) if public_base else str(request.url)
        if not verify_twilio_signature(settings.twilio_auth_token, sig, url, form_dict):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        reply = handle_inbound(form_dict, db)
    except Exception:
        reply = "Sorry, something went wrong. Try again."

    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{reply}</Message></Response>'
    return HTMLResponse(content=twiml, media_type="application/xml")


# ── WATI delivery status webhook ──────────────────────────────────────────────

_WATI_STATUS_MAP = {
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
    "undelivered": "failed",
}


@router.post("/webhook/wati/delivery")
async def wati_delivery_webhook(
    request: Request,
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    """WATI calls this for message status updates (sent/delivered/read/failed)."""
    # Optional HMAC verification if WATI_WEBHOOK_SECRET is set
    secret = os.getenv("WATI_WEBHOOK_SECRET", "")
    if secret:
        sig = request.headers.get("X-Wati-Signature", "")
        body = await request.body()
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=403, detail="Invalid signature")
        payload = json.loads(body)
    else:
        payload = await request.json()

    # WATI webhook payload shape:
    # {"eventType": "message_status", "payload": {"id": "wamid.xxx", "status": "delivered", ...}}
    event = payload.get("eventType", "")
    if event != "message_status":
        return {"ok": True, "skipped": True}

    inner = payload.get("payload", payload)
    wamid = inner.get("id") or inner.get("messageId") or ""
    raw_status = (inner.get("status") or "").lower()
    status = _WATI_STATUS_MAP.get(raw_status)

    if not wamid or not status:
        return {"ok": True, "skipped": True}

    log_row = db.find_notification_log_by_provider_id(wamid)
    if not log_row:
        return {"ok": True, "not_found": True}

    delivered_at = iso(utc_now()) if status == "delivered" else None
    read_at = iso(utc_now()) if status == "read" else None
    db.update_notification_status(
        log_row["id"],
        status,
        delivered_at=delivered_at,
        read_at=read_at,
    )
    return {"ok": True, "log_id": log_row["id"], "status": status}


# ── MSG91 delivery status webhook ─────────────────────────────────────────────

_MSG91_STATUS_MAP = {
    "delivered": "delivered",
    "failed": "failed",
    "rejected": "failed",
    "sent": "sent",
    "read": "read",
}


@router.post("/webhook/msg91/inbound")
async def msg91_inbound_webhook(
    request: Request,
    db: Any = Depends(get_db),
) -> dict:
    """MSG91 fires this when a user sends a WhatsApp message to the business number."""
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    # MSG91 inbound payload: {"from": "917464026177", "message": "Hi", "type": "text", ...}
    sender = (payload.get("from") or payload.get("sender") or "").strip()
    if not sender:
        return {"ok": True}

    phone = "+" + sender.lstrip("+")
    user = db.get_user_by_phone(phone)

    from ..services.notifications import send_msg91_session_message, _msg91_whatsapp_key
    auth_key = _msg91_whatsapp_key()

    if user:
        db.set_whatsapp_verified(str(user["id"]), phone)
        name = user.get("name") or "there"
        msg = (
            f"Hi {name}! \U0001f44b Your WhatsApp alerts are now active on SuperSahayak Legal.\n\n"
            "You'll receive alerts when your cases appear in the cause list or display board.\n\n"
            "Reply HELP to see available commands."
        )
    else:
        msg = (
            "Hi! SuperSahayak Legal helps advocates track High Court cases in real time.\n\n"
            "Create your account at legal.supersahayak.com to get case alerts on WhatsApp."
        )

    if auth_key:
        send_msg91_session_message(phone, msg, auth_key)

    return {"ok": True}


@router.post("/webhook/msg91/delivery")
async def msg91_delivery_webhook(
    request: Request,
    db: Any = Depends(get_db),
) -> dict:
    """MSG91 calls this for WhatsApp message delivery status updates."""
    payload = await request.json()

    # MSG91 bulk callback: {"reports": [{"requestId": "...", "status": "delivered", ...}]}
    reports = payload if isinstance(payload, list) else payload.get("reports", [payload])

    updated = 0
    for report in reports:
        request_id = report.get("requestId") or report.get("msgId") or ""
        raw_status = (report.get("status") or "").lower()
        status = _MSG91_STATUS_MAP.get(raw_status)
        if not request_id or not status:
            continue

        log_row = db.find_notification_log_by_provider_id(request_id)
        if not log_row:
            continue

        delivered_at = iso(utc_now()) if status == "delivered" else None
        read_at = iso(utc_now()) if status == "read" else None
        db.update_notification_status(
            log_row["id"],
            status,
            delivered_at=delivered_at,
            read_at=read_at,
        )
        updated += 1

    return {"ok": True, "updated": updated}


# ── Telegram webhook ───────────────────────────────────────────────────────────


@router.post("/webhooks/telegram")
async def telegram_webhook(
    request: Request,
    db: Any = Depends(get_db),
) -> dict:
    """Telegram calls this for every update (user messages, callback queries).

    Must return 200 quickly — heavy processing happens asynchronously.
    """
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    # Handle /start and /help commands
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat", {}).get("id")
    user_tg = message.get("from", {})

    if chat_id and text:
        telegram_id = str(user_tg.get("id", chat_id))
        if text.startswith("/start"):
            _handle_telegram_start(db, chat_id, user_tg, text)
        else:
            from ..bots.telegram_bot import handle_command
            reply = handle_command(db, telegram_id, text)
            if reply:
                _send_tg(chat_id, reply)

    # Callback queries (inline keyboard button presses) — acknowledge immediately
    callback_query = update.get("callback_query")
    if callback_query:
        _handle_callback_query(db, callback_query)

    return {"ok": True}


def _send_tg(chat_id: int, text: str) -> None:
    import os
    import httpx as _httpx
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return
    try:
        _httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
            timeout=8,
        )
    except Exception:
        pass


def _handle_telegram_start(db: Any, chat_id: int, tg_user: dict, text: str) -> None:
    """Link Telegram chat_id to a SuperSahayak user account if possible."""
    import os
    import httpx as _httpx
    from datetime import datetime, timezone, timedelta

    username = tg_user.get("username", "")
    first_name = tg_user.get("first_name", "")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    _IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(_IST).strftime("%d %b %Y, %I:%M %p IST")

    # Try to link and check if user already exists
    user_found = False
    if username:
        try:
            db.set_telegram_chat_id_by_username(username, chat_id)
        except Exception:
            pass

    # Check if this chat_id is already linked to a user
    try:
        linked_user = db.get_user_by_telegram_chat_id(chat_id)
        user_found = linked_user is not None
    except Exception:
        user_found = False

    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "SuperSahayakLegalBot")

    if user_found:
        name = linked_user.get("name") or first_name or "there"
        reply = (
            f"👋 Welcome back, {name}!\n\n"
            f"✅ Your account is linked to SuperSahayak Legal.\n\n"
            f"*Commands:*\n"
            f"/today — active courts right now\n"
            f"/watch <room> <serial> — set serial alert\n"
            f"/list — your active alerts\n"
            f"/help — all commands\n\n"
            f"🕐 {now_ist}"
        )
    else:
        reply = (
            f"👋 Welcome{' ' + first_name if first_name else ''} to SuperSahayak Legal!\n\n"
            f"To receive court alerts here, link your Telegram account:\n"
            f"1️⃣ Log in at [legal.supersahayak.com](https://legal.supersahayak.com)\n"
            f"2️⃣ Go to Settings → Telegram\n"
            f"3️⃣ Enter your username: @{username or 'your_username'}\n\n"
            f"Once linked, use /today to see live court data.\n\n"
            f"🕐 {now_ist}"
        )

    if token:
        try:
            _httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": reply, "parse_mode": "Markdown",
                      "disable_web_page_preview": True},
                timeout=5,
            )
        except Exception:
            pass


def _handle_callback_query(db: Any, callback_query: dict) -> None:
    import os
    import httpx as _httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    query_id = callback_query.get("id", "")
    if token and query_id:
        try:
            _httpx.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": query_id},
                timeout=5,
            )
        except Exception:
            pass


# ── Unsubscribe endpoint ───────────────────────────────────────────────────────


@router.get("/unsubscribe")
async def unsubscribe_email(
    token: str,
    db: Any = Depends(get_db),
) -> dict:
    """One-click unsubscribe from email alerts via token in email footer."""
    if not token:
        return {"ok": False, "detail": "Missing token"}
    try:
        user = db.get_user_by_unsubscribe_token(token)
        if not user:
            return {"ok": False, "detail": "Invalid token"}
        db.set_email_invalid(str(user["id"]))
        return {"ok": True, "message": "You have been unsubscribed from email alerts."}
    except Exception as exc:
        log.warning("unsubscribe: error", exc=str(exc))
        return {"ok": False, "detail": "Error processing request"}


# ── Resend bounce webhook ─────────────────────────────────────────────────────


@router.post("/webhooks/resend")
async def resend_bounce_webhook(
    request: Request,
    db: Any = Depends(get_db),
) -> dict:
    """Resend calls this for bounce/complaint events.

    On hard bounce (type=email.bounced): set email_valid=0 on the user.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    event_type = payload.get("type", "")
    if event_type not in ("email.bounced", "email.complained"):
        return {"ok": True, "skipped": True}

    data = payload.get("data", {})
    to_addresses = data.get("to", [])
    if isinstance(to_addresses, str):
        to_addresses = [to_addresses]

    updated = 0
    for email in to_addresses:
        try:
            user = db.get_user_by_email(email)
            if user:
                db.set_email_invalid(str(user["id"]))
                log.warning("resend_bounce: marked email_valid=0", email=email, event=event_type)
                updated += 1
        except Exception as exc:
            log.warning("resend_bounce: db error", exc=str(exc), email=email)

    return {"ok": True, "updated": updated}

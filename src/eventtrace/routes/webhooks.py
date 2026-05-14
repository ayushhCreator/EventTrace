from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

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
            "Create your account at supersahayak.in to get case alerts on WhatsApp."
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

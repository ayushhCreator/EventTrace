from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

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

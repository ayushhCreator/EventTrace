from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from ..schemas.alerts import AlertRequest
from ..services.deps import get_db
from .utils import today_ist

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.post("/alert", status_code=201)
def create_alert(req: AlertRequest, x_api_key: str | None = Header(default=None), db: Any = Depends(get_db)) -> dict:
    alert_api_key = os.getenv("CHD_ALERT_API_KEY", "")
    if alert_api_key and x_api_key != alert_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key")

    date = req.hearing_date or today_ist()
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="hearing_date must be YYYY-MM-DD")

    phone = (req.phone or "").strip()
    if req.contact_type == "whatsapp":
        if not phone.startswith("+"):
            phone = "+" + phone

    sub_id = db.add_subscription(
        telegram_id="",
        room_no=req.room_no,
        target_serial=req.target_serial,
        look_ahead=req.look_ahead,
        hearing_date=date,
        contact_type=req.contact_type,
        display_name=req.display_name,
        phone=phone or None,
    )
    alert_at = req.target_serial - req.look_ahead
    bot_cmd = f"/watch {req.room_no} {req.target_serial} {req.look_ahead} {date}"
    return {
        "id": sub_id,
        "room_no": req.room_no,
        "target_serial": req.target_serial,
        "alert_at": alert_at,
        "hearing_date": date,
        "contact_type": req.contact_type,
        "telegram_command": bot_cmd,
    }


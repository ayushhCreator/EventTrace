"""WhatsApp bot via Twilio.

Outbound alerts:   send_whatsapp_sync()  — called from run_monitor
Inbound commands:  handle_inbound()      — called from POST /webhook/whatsapp

Commands (same logic as Telegram bot):
  WATCH <room> <serial> [ahead] [date]
  UNWATCH <room>
  STATUS <room>
  LIST
  TODAY
  DAILY
  HELP
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .db import DB

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


# ── Outbound sender ───────────────────────────────────────────────────────────

def send_whatsapp_sync(
    account_sid: str,
    auth_token: str,
    from_number: str,   # "whatsapp:+14155238886"
    to_phone: str,      # "+919876543210"  (E.164, no whatsapp: prefix)
    body: str,
) -> None:
    """Send a WhatsApp message via Twilio REST API (blocking)."""
    to_wa = f"whatsapp:{to_phone}" if not to_phone.startswith("whatsapp:") else to_phone
    creds = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    resp = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
        data={"From": from_number, "To": to_wa, "Body": body},
        headers={"Authorization": f"Basic {creds}"},
        timeout=10,
    )
    resp.raise_for_status()


def _build_alert_message(payload: dict) -> str:
    room = payload["room_no"]
    current = payload["current_serial"]
    target = payload["target_serial"]
    zoom_url = payload.get("zoom_url", "")
    lines = [
        f"🔔 *Alert — Court Room {room}*",
        f"Serial now at *{current}* — your case is *{target}*",
        "➡️ Time to get ready!",
    ]
    if zoom_url:
        lines += ["", f"Join VC: {zoom_url}"]
    else:
        lines.append("(In-person court — no VC link)")
    return "\n".join(lines)


# ── Helpers (shared with Telegram bot logic) ──────────────────────────────────

def _get_room_serial(db: DB, room_no: str) -> int | None:
    states = db.list_current_state()
    serials: list[int] = []
    for entry in states:
        data = entry.get("data", {})
        if str(data.get("room_no", "")) == room_no:
            try:
                parts = str(data.get("cause_list_sr_no", "")).split("-")
                serials.append(int(parts[-1]))
            except (TypeError, ValueError):
                pass
    return max(serials) if serials else None


def _all_rooms_summary(db: DB) -> list[dict]:
    states = db.list_current_state()
    rooms: dict[str, dict] = {}
    for entry in states:
        data = entry.get("data", {})
        room_no = str(data.get("room_no", "")).strip()
        if not room_no:
            continue
        try:
            serial = int(str(data.get("cause_list_sr_no", "")).split("-")[-1])
        except (TypeError, ValueError):
            serial = 0
        if room_no not in rooms or serial > rooms[room_no]["serial"]:
            rooms[room_no] = {"room_no": room_no, "serial": serial}
    return sorted(rooms.values(), key=lambda r: r["room_no"].zfill(6))


# ── Inbound command parser ────────────────────────────────────────────────────

def handle_inbound(form: dict[str, Any], db: DB) -> str:
    """Parse a Twilio inbound WhatsApp message and return the reply text."""
    raw_from = form.get("From", "")
    # from_  = "whatsapp:+919876543210"  →  phone = "+919876543210"
    phone = raw_from.replace("whatsapp:", "").strip()
    body = form.get("Body", "").strip()

    if not body:
        return _help_text()

    parts = body.split()
    cmd = parts[0].upper()

    if cmd in ("HELP", "START", "HI", "HELLO"):
        return _help_text()

    if cmd == "TODAY":
        return _cmd_today(db)

    if cmd == "DAILY":
        return _cmd_daily(db, phone)

    if cmd == "STATUS" and len(parts) >= 2:
        return _cmd_status(db, parts[1])

    if cmd == "WATCH" and len(parts) >= 3:
        return _cmd_watch(db, phone, parts)

    if cmd == "UNWATCH" and len(parts) >= 2:
        return _cmd_unwatch(db, phone, parts[1])

    if cmd == "LIST":
        return _cmd_list(db, phone)

    return (
        "Command not recognised.\n\n"
        "Try: WATCH 8 205  or  STATUS 8  or  LIST\n"
        "Send HELP for full guide."
    )


def _help_text() -> str:
    return (
        "🏛 *Eventtrace — Calcutta High Court Alerts*\n\n"
        "Commands:\n"
        "TODAY — all active courts\n"
        "DAILY — your alerts + all active courts\n"
        "STATUS 8 — current serial for room 8\n"
        "WATCH 8 205 — alert when room 8 reaches serial 200\n"
        "WATCH 8 205 3 — alert 3 before (serial 202)\n"
        "WATCH 8 11 5 2026-04-25 — for tomorrow's hearing\n"
        "UNWATCH 8 — cancel alert\n"
        "LIST — your active alerts\n"
        "HELP — this guide"
    )


def _cmd_today(db: DB) -> str:
    rooms = _all_rooms_summary(db)
    if not rooms:
        return "No court data right now. Court may not be in session."
    vc_links = db.get_vc_zoom_links(_today_ist())
    lines = ["📋 Active courts:\n"]
    for r in rooms:
        vc = "📹" if r["room_no"] in vc_links else "🏛"
        lines.append(f"{vc} Room {r['room_no']} — Serial {r['serial']}")
    lines.append("\nSend WATCH <room> <serial> to set alert.")
    return "\n".join(lines)


def _cmd_daily(db: DB, phone: str) -> str:
    today = _today_ist()
    subs = _list_wa_subscriptions(db, phone)
    rooms = _all_rooms_summary(db)
    vc_links = db.get_vc_zoom_links(today)

    lines: list[str] = []

    if subs:
        lines.append("🔔 Your alerts today:\n")
        for s in subs:
            date_str = s.get("hearing_date") or "any day"
            if date_str not in (today, "any day"):
                continue  # skip alerts for other dates
            current = _get_room_serial(db, str(s["room_no"]))
            alert_at = s["target_serial"] - s["look_ahead"]
            cur_str = f" · now at {current}" if current is not None else ""
            lines.append(
                f"• Room {s['room_no']} — serial {s['target_serial']} · alert at {alert_at}{cur_str}"
            )
        if len(lines) == 1:
            lines.append("(none for today)")
        lines.append("")

    if not rooms:
        lines.append("No court data right now.")
    else:
        lines.append("Active courts:\n")
        for r in rooms:
            vc = "📹" if r["room_no"] in vc_links else "🏛"
            lines.append(f"{vc} Room {r['room_no']} — Serial {r['serial']}")

    return "\n".join(lines)


def _cmd_status(db: DB, room_no: str) -> str:
    current = _get_room_serial(db, room_no)
    if current is None:
        return f"Room {room_no}: no data. Send TODAY to see active rooms."
    vc_links = db.get_vc_zoom_links(_today_ist())
    lines = [f"🏛 Room {room_no} — Serial: {current}"]
    if room_no in vc_links:
        lines.append(f"📹 VC: {vc_links[room_no]}")
    lines.append(f"\nSet alert: WATCH {room_no} <your serial>")
    return "\n".join(lines)


def _cmd_watch(db: DB, phone: str, parts: list[str]) -> str:
    import re as _re
    room_no = parts[1]
    try:
        target = int(parts[2])
        ahead = int(parts[3]) if len(parts) >= 4 else 5
    except (ValueError, IndexError):
        return "Usage: WATCH <room> <serial> [ahead]\nExample: WATCH 8 205"

    if ahead < 0 or ahead > 50:
        return "ahead must be 0–50."

    hearing_date = _today_ist()
    if len(parts) >= 5:
        candidate = parts[4]
        if _re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
            hearing_date = candidate

    db.remove_whatsapp_subscription(phone, room_no)
    db.add_subscription(
        telegram_id="",
        room_no=room_no,
        target_serial=target,
        look_ahead=ahead,
        hearing_date=hearing_date,
        contact_type="whatsapp",
        phone=phone,
    )
    alert_at = target - ahead
    return (
        f"✅ Alert set for Room {room_no}\n"
        f"Hearing date: {hearing_date}\n"
        f"Your serial: {target}\n"
        f"Alert fires when serial ≥ {alert_at}\n\n"
        f"Cancel: UNWATCH {room_no}"
    )


def _cmd_unwatch(db: DB, phone: str, room_no: str) -> str:
    db.remove_whatsapp_subscription(phone, room_no)
    return f"✓ Stopped watching Room {room_no}."


def _cmd_list(db: DB, phone: str) -> str:
    # WhatsApp subscriptions are keyed by phone, not telegram_id
    # We query by phone column
    subs = _list_wa_subscriptions(db, phone)
    if not subs:
        return "No active alerts.\n\nSend WATCH <room> <serial> to set one."
    lines = ["🔔 Your active alerts:\n"]
    for s in subs:
        current = _get_room_serial(db, str(s["room_no"]))
        cur_str = f" (now at {current})" if current is not None else ""
        date_str = s.get("hearing_date") or "any day"
        lines.append(
            f"• Room {s['room_no']} — serial {s['target_serial']}\n"
            f"  Date: {date_str} · Alert at {s['target_serial'] - s['look_ahead']}{cur_str}"
        )
    lines.append("\nCancel: UNWATCH <room>")
    return "\n".join(lines)


def _list_wa_subscriptions(db: DB, phone: str) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM subscriptions WHERE active=1 AND contact_type='whatsapp' AND phone=?",
            (phone,),
        ).fetchall()
    return [dict(r) for r in rows]

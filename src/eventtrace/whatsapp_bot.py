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
    today = _today_ist()
    states = db.list_current_state()
    serials: list[int] = []
    for entry in states:
        data = entry.get("data", {})
        if data.get("hearing_date") != today:
            continue
        if str(data.get("room_no", "")) == room_no:
            try:
                parts = str(data.get("cause_list_sr_no", "")).split("-")
                serials.append(int(parts[-1]))
            except (TypeError, ValueError):
                pass
    return max(serials) if serials else None


def _all_rooms_summary(db: DB) -> list[dict]:
    today = _today_ist()
    states = db.list_current_state()
    rooms: dict[str, dict] = {}
    for entry in states:
        data = entry.get("data", {})
        if data.get("hearing_date") != today:
            continue
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

    if cmd in ("HELP", "START", "HI", "HII", "HIII", "HELLO", "HEY", "NAMASTE", "NAM"):
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

    if cmd in ("CAUSELIST", "CAUSE"):
        return _cmd_causelist(db)

    if cmd == "ZOOM" and len(parts) >= 2:
        return _cmd_zoom(db, parts[1])

    return (
        "Command not recognised.\n\n"
        "Try: WATCH 8 205  or  STATUS 8  or  LIST\n"
        "Send HELP for full guide."
    )


def _help_text() -> str:
    return (
        "🏛 *Eventtrace — Calcutta High Court Alerts*\n\n"
        "Each court room has its own serial sequence (1, 2, 3…).\n"
        "You need *room number + your serial* from the cause list.\n\n"
        "Commands:\n"
        "TODAY — active courts on live board (today only)\n"
        "CAUSELIST — today's courts with VC links\n"
        "ZOOM 8 — Zoom link for room 8\n"
        "DAILY — your alerts + all active courts\n"
        "STATUS 8 — current serial for room 8\n"
        "WATCH 8 205 — alert for Room 8, your serial is 205\n"
        "WATCH 8 205 3 — alert 3 serials before 205 (at 202)\n"
        "WATCH 8 205 5 2026-04-28 — for a future date\n"
        "UNWATCH 8 — cancel alert for Room 8 (use room number, not serial)\n"
        "LIST — your active alerts\n"
        "HELP — this guide"
    )


def _monitor_stale_warning(db: DB) -> str:
    """Returns a warning string if monitor hasn't polled in >5 min, else ''."""
    last = db.get_monitor_state("last_successful_poll")
    if not last:
        return ""
    try:
        from datetime import timezone as _tz
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        age_min = (datetime.now(_tz.utc) - last_dt).total_seconds() / 60
        if age_min > 5:
            return f"\n\n⚠️ Monitor last updated {int(age_min)}m ago — data may be stale."
    except Exception:
        pass
    return ""


def _cmd_today(db: DB) -> str:
    today = _today_ist()
    rooms = _all_rooms_summary(db)
    warning = _monitor_stale_warning(db)
    vc_links = db.get_vc_zoom_links(today)
    vc_count = len(vc_links)
    now_ist = datetime.now(_IST)
    board_active = db.get_monitor_state("board_active")

    # Board known to be empty right now
    if board_active == "0":
        if now_ist.hour < 10 or (now_ist.hour == 10 and now_ist.minute < 30):
            msg = (
                f"🏛 Board not live yet for {today}.\n"
                "Court display usually starts at 10:30 AM IST.\n\n"
            )
        else:
            msg = f"🏛 Board closed for {today}. Court session has ended.\n\n"
        if vc_count:
            msg += f"📋 Cause list has *{vc_count} courts* with VC links.\nSend CAUSELIST to see them."
        else:
            msg += "Today's cause list not published yet.\nCheck calcuttahighcourt.gov.in after 9 AM."
        if warning:
            msg += warning
        return msg

    # Board state unknown (monitor never ran) or active but no today rows yet
    if not rooms:
        if now_ist.hour < 10 or (now_ist.hour == 10 and now_ist.minute < 30):
            msg = (
                f"🏛 Board not live yet for {today}.\n"
                "Court display usually starts at 10:30 AM IST.\n\n"
            )
        else:
            msg = f"🏛 No court data on board for {today} yet.\n\n"
        if vc_count:
            msg += f"📋 Today's cause list has *{vc_count} courts* with VC links.\nSend CAUSELIST to see them."
        else:
            msg += "Today's cause list not published yet.\nCheck calcuttahighcourt.gov.in after 9 AM."
        if warning:
            msg += warning
        return msg

    lines = [f"📋 Active courts ({today}):\n"]
    for r in rooms:
        vc = "📹" if r["room_no"] in vc_links else "🏛"
        lines.append(f"{vc} Room {r['room_no']} — Serial {r['serial']}")
    lines.append("\nSend WATCH [room] [serial] to set alert.")
    if warning:
        lines.append(warning)
    return "\n".join(lines)


def _cmd_causelist(db: DB) -> str:
    today = _today_ist()
    vc_links = db.get_vc_zoom_links(today)
    if not vc_links:
        return (
            f"📋 No cause list data for {today} yet.\n"
            "The cause list is usually published by 9–10 AM on court days.\n"
            "Check: calcuttahighcourt.gov.in"
        )
    rooms = sorted(vc_links.keys(), key=lambda r: r.zfill(6))
    room_list = ", ".join(f"Room {r}" for r in rooms)
    return (
        f"📋 Cause list — {today} ({len(rooms)} courts with VC):\n\n"
        f"{room_list}\n\n"
        "Send *ZOOM [room]* for the link.\nExample: ZOOM 8"
    )


def _cmd_zoom(db: DB, room_no: str) -> str:
    today = _today_ist()
    vc_links = db.get_vc_zoom_links(today)
    # match regardless of leading zeros
    canonical = room_no.lstrip("0") or room_no
    url = next((vc_links[k] for k in vc_links if (k.lstrip("0") or k) == canonical), None)
    if not url:
        return f"📹 No VC link for Room {room_no} on {today}.\nSend CAUSELIST to see available rooms."
    return f"📹 Room {room_no} — {today}\n{url}"


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
    warning = _monitor_stale_warning(db)
    if current is None:
        return f"Room {room_no}: no data. Send TODAY to see active rooms." + warning
    vc_links = db.get_vc_zoom_links(_today_ist())
    lines = [f"🏛 Room {room_no} — Serial: {current}"]
    if room_no in vc_links:
        lines.append(f"📹 VC: {vc_links[room_no]}")
    lines.append(f"\nSet alert: WATCH {room_no} [your serial]")
    if warning:
        lines.append(warning)
    return "\n".join(lines)


def _cmd_watch(db: DB, phone: str, parts: list[str]) -> str:
    import re as _re
    room_no = parts[1]
    try:
        target = int(parts[2])
        ahead = int(parts[3]) if len(parts) >= 4 else 5
    except (ValueError, IndexError):
        return "Usage: WATCH [room] [serial] [ahead]\nExample: WATCH 8 205"

    if ahead < 0 or ahead > 50:
        return "ahead must be 0–50."
    ahead = min(ahead, target - 1)  # threshold must be >= 1

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
    msg = (
        f"✅ Alert set for Room {room_no}\n"
        f"Hearing date: {hearing_date}\n"
        f"Your serial: {target}\n"
        f"Alert fires when serial ≥ {alert_at}\n\n"
        f"Cancel: UNWATCH {room_no}"
    )

    # Fire alert immediately if board is live and serial already at/past threshold
    current = _get_room_serial(db, room_no)
    if current is not None and current >= alert_at:
        today_str = _today_ist()
        vc_links = db.get_vc_zoom_links(today_str)
        alert = _build_alert_message({
            "room_no": room_no,
            "current_serial": current,
            "target_serial": target,
            "zoom_url": vc_links.get(room_no, ""),
        })
        if current >= target:
            note = f"⚠️ Your case serial ({target}) may already have been called."
        else:
            note = f"⚠️ Alert threshold ({alert_at}) already passed."
        return f"{msg}\n\n{note}\n\n{alert}"

    return msg


def _cmd_unwatch(db: DB, phone: str, room_no: str) -> str:
    removed = db.remove_whatsapp_subscription(phone, room_no)
    if not removed:
        subs = _list_wa_subscriptions(db, phone)
        if subs:
            active_rooms = ", ".join(f"Room {s['room_no']}" for s in subs)
            return f"No active alert for Room {room_no}.\n\nYour active alerts: {active_rooms}"
        return f"No active alert for Room {room_no}.\n\nSend LIST to see your alerts."
    return f"✓ Stopped watching Room {room_no}."


def _cmd_list(db: DB, phone: str) -> str:
    subs = _list_wa_subscriptions(db, phone)
    warning = _monitor_stale_warning(db)
    if not subs:
        return "No active alerts.\n\nSend WATCH [room] [serial] to set one." + warning
    lines = ["🔔 Your active alerts:\n"]
    for s in subs:
        current = _get_room_serial(db, str(s["room_no"]))
        cur_str = f" (now at {current})" if current is not None else ""
        date_str = s.get("hearing_date") or "any day"
        lines.append(
            f"• Room {s['room_no']} — serial {s['target_serial']}\n"
            f"  Date: {date_str} · Alert at {s['target_serial'] - s['look_ahead']}{cur_str}"
        )
    lines.append("\nCancel: UNWATCH [room]")
    if warning:
        lines.append(warning)
    return "\n".join(lines)


def _list_wa_subscriptions(db: DB, phone: str) -> list[dict]:
    with db.connect() as con:
        rows = con.execute(
            "SELECT * FROM subscriptions WHERE active=1 AND contact_type='whatsapp' AND phone=?",
            (phone,),
        ).fetchall()
    return [dict(r) for r in rows]

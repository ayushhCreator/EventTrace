"""Telegram bot for @Eventtrace_bot.

Commands:
  /start  /help   — onboarding guide
  /today          — all active courts right now (room, serial, judge)
  /status <room>  — current serial + VC link for one room
  /watch <room> <serial> [ahead]  — set alert
  /unwatch <room> — cancel alert
  /list           — your active alerts

Run:  chd-bot
Env:  TELEGRAM_TOKEN=<bot_token>
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .config import Settings
from .db import DB

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


# ── Notification helper (called from run_monitor) ────────────────────────────

def send_notification_sync(token: str, telegram_id: str, payload: dict) -> None:
    """Blocking HTTP send — called from the monitor thread."""
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
        lines += ["", f"*Join VC:*\n{zoom_url}"]
    else:
        lines.append("_(In-person court — no VC link)_")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = httpx.post(
        url,
        json={"chat_id": telegram_id, "text": "\n".join(lines), "parse_mode": "Markdown"},
        timeout=10,
    )
    resp.raise_for_status()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_db(settings: Settings) -> DB:
    db = DB(settings.db_path)
    db.ensure_schema()
    return db


def _get_room_data(db: DB, room_no: str) -> tuple[int | None, str]:
    """Returns (current_max_serial, judge_name) for a room, or (None, '')."""
    states = db.list_current_state()
    serials: list[int] = []
    judge = ""
    for entry in states:
        data = entry.get("data", {})
        if str(data.get("room_no", "")) == room_no:
            try:
                sr = data.get("cause_list_sr_no", "")
                parts = str(sr).split("-")
                serials.append(int(parts[-1]))
            except (TypeError, ValueError):
                pass
            if not judge:
                judge = data.get("judge_name", "") or data.get("bench_name", "")
    return (max(serials) if serials else None, judge)


def _all_rooms_summary(db: DB) -> list[dict]:
    """Returns list of {room_no, serial, judge} sorted by room_no."""
    states = db.list_current_state()
    rooms: dict[str, dict] = {}
    for entry in states:
        data = entry.get("data", {})
        room_no = str(data.get("room_no", "")).strip()
        if not room_no:
            continue
        try:
            sr = data.get("cause_list_sr_no", "")
            serial = int(str(sr).split("-")[-1])
        except (TypeError, ValueError):
            serial = 0
        if room_no not in rooms or serial > rooms[room_no]["serial"]:
            rooms[room_no] = {
                "room_no": room_no,
                "serial": serial,
                "judge": data.get("judge_name", "") or data.get("bench_name", ""),
            }
    return sorted(rooms.values(), key=lambda r: r["room_no"].zfill(6))


# ── Command handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Deep link from UI: /start watch_<room>_<serial>_<ahead>_<date>
    # e.g. /start watch_8_205_5_2026-04-25
    payload = (ctx.args[0] if ctx.args else "").strip()
    if payload.startswith("watch_"):
        await _handle_deep_link_watch(update, ctx, payload)
        return

    text = (
        "👋 *Welcome to Eventtrace Bot*\n"
        "Real-time Calcutta High Court display board alerts.\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "*How to get notified in 3 steps:*\n\n"
        "*1.* See which room your case is in:\n"
        "   → `/today` — shows all active rooms + current serial\n\n"
        "*2.* Find your case serial number:\n"
        "   → Check the cause list on the CHC website\n"
        "   → Or `/status 8` to see room 8's current serial\n\n"
        "*3.* Set an alert:\n"
        "   → `/watch 8 45` — alert when room 8 reaches serial 40\n"
        "   _(default: alert 5 serials before your case)_\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "*All commands:*\n"
        "/today — active courts right now\n"
        "/daily — your alerts + all active courts\n"
        "/status `<room>` — current serial for a room\n"
        "/watch `<room> <serial>` — set alert\n"
        "/unwatch `<room>` — cancel alert\n"
        "/list — your active alerts\n"
        "/help — show this guide"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def _handle_deep_link_watch(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, payload: str
) -> None:
    """Handle /start watch_<room>_<serial>_<ahead>_<date> from UI deep link."""
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)

    # payload = "watch_8_205_5_2026-04-25"
    parts = payload.split("_", 1)[1].split("_")  # ["8","205","5","2026-04-25"]
    if len(parts) < 2:
        await update.message.reply_text("Invalid alert link. Use /watch to set an alert manually.")
        return

    room_no = parts[0]
    try:
        target_serial = int(parts[1])
        look_ahead = int(parts[2]) if len(parts) >= 3 else 5
        hearing_date = parts[3] if len(parts) >= 4 else _today_ist()
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid alert link. Use /watch to set an alert manually.")
        return

    db.remove_subscription(telegram_id, room_no)
    db.add_subscription(
        telegram_id, room_no, target_serial, look_ahead,
        hearing_date=hearing_date,
    )
    alert_at = target_serial - look_ahead
    current, _ = _get_room_data(db, room_no)
    vc_links = db.get_vc_zoom_links(_today_ist())

    lines = [
        "✅ *Alert linked to your Telegram account!*",
        f"Room: *{room_no}* · Date: *{hearing_date}*",
        f"Your serial: *{target_serial}* · Alert at: *{alert_at}*",
    ]
    if current is not None:
        lines.append(f"Current serial: *{current}*")
    if room_no in vc_links:
        lines.append("📹 VC link available — will be sent with alert")
    lines += ["", "Cancel: `/unwatch " + room_no + "`"]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    vc_links = db.get_vc_zoom_links(_today_ist())
    rooms = _all_rooms_summary(db)

    if not rooms:
        await update.message.reply_text(
            "📋 No court data available right now.\n"
            "Court may not be in session, or the monitor is not running."
        )
        return

    lines = ["📋 *Active courts right now:*\n"]
    for r in rooms:
        vc = "📹" if r["room_no"] in vc_links else "🏛"
        judge_short = r["judge"].replace("HON'BLE ", "").replace("JUSTICE ", "").strip()
        # Truncate long judge names
        if len(judge_short) > 40:
            judge_short = judge_short[:38] + "…"
        serial_str = f"Serial: *{r['serial']}*" if r["serial"] else "Serial: —"
        lines.append(f"{vc} *Room {r['room_no']}* — {serial_str}")
        if judge_short:
            lines.append(f"   _{judge_short}_")

    lines += [
        "",
        "📹 = VC available  🏛 = in-person",
        "Use `/status <room>` for details or `/watch <room> <serial>` to set alert.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    today = _today_ist()

    subs = db.list_user_subscriptions(telegram_id)
    rooms = _all_rooms_summary(db)
    vc_links = db.get_vc_zoom_links(today)

    lines: list[str] = []

    if subs:
        lines.append("🔔 *Your alerts today:*\n")
        shown = 0
        for s in subs:
            date_str = s.get("hearing_date") or "any day"
            if date_str not in (today, "any day"):
                continue
            current, _ = _get_room_data(db, str(s["room_no"]))
            alert_at = s["target_serial"] - s["look_ahead"]
            cur_str = f" · now at {current}" if current is not None else ""
            lines.append(
                f"• *Room {s['room_no']}* — serial {s['target_serial']} · alert at {alert_at}{cur_str}"
            )
            shown += 1
        if shown == 0:
            lines.append("_(none for today)_")
        lines.append("")

    if not rooms:
        lines.append("No court data right now.")
    else:
        lines.append("*Active courts:*\n")
        for r in rooms:
            vc = "📹" if r["room_no"] in vc_links else "🏛"
            judge_short = r["judge"].replace("HON'BLE ", "").replace("JUSTICE ", "").strip()
            if len(judge_short) > 40:
                judge_short = judge_short[:38] + "…"
            lines.append(f"{vc} *Room {r['room_no']}* — Serial: *{r['serial']}*")
            if judge_short:
                lines.append(f"   _{judge_short}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    args = ctx.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/status <room_no>`\n\nExample: `/status 8`\n\nUse /today to see all rooms.",
            parse_mode="Markdown",
        )
        return

    room_no = args[0]
    current, judge = _get_room_data(db, room_no)

    if current is None:
        await update.message.reply_text(
            f"Room {room_no}: no data.\n"
            "Court may not be in session, or room number is wrong.\n\n"
            "Use /today to see all active rooms."
        )
        return

    vc_links = db.get_vc_zoom_links(_today_ist())
    lines = [f"🏛 *Room {room_no}*", f"Current serial: *{current}*"]
    if judge:
        judge_clean = judge.replace("HON'BLE ", "").replace("JUSTICE ", "").strip()
        lines.append(f"_{judge_clean}_")
    if room_no in vc_links:
        lines += ["", f"📹 *VC Link:*\n{vc_links[room_no]}"]
    else:
        lines.append("_(In-person court — no VC)_")
    lines += ["", f"Set alert: `/watch {room_no} <your_serial>`"]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    args = ctx.args or []

    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/watch <room_no> <your_serial> [alert_before] [date]`\n\n"
            "*room\\_no* — court room number (use /today to find it)\n"
            "*your\\_serial* — your case's serial number from the cause list\n"
            "*alert\\_before* — how many serials before to alert (default: 5)\n"
            "*date* — YYYY\\-MM\\-DD, default today\n\n"
            "Example: `/watch 8 45` — alert today when room 8 reaches serial 40\n"
            "Example: `/watch 8 45 3` — alert when room 8 reaches serial 42\n"
            "Example: `/watch 8 11 5 2026\\-04\\-25` — for tomorrow's hearing",
            parse_mode="Markdown",
        )
        return

    room_no = args[0]
    try:
        target_serial = int(args[1])
        look_ahead = int(args[2]) if len(args) >= 3 else 5
    except ValueError:
        await update.message.reply_text("Serial and alert\\_before must be numbers.\n\nExample: `/watch 8 45`", parse_mode="Markdown")
        return

    if look_ahead < 0 or look_ahead > 50:
        await update.message.reply_text("alert\\_before must be between 0 and 50.", parse_mode="Markdown")
        return

    # Optional 4th arg: hearing date (YYYY-MM-DD)
    hearing_date = _today_ist()
    if len(args) >= 4:
        import re
        date_arg = args[3]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_arg):
            await update.message.reply_text(
                "Date must be YYYY\\-MM\\-DD format, e.g. `2026-04-25`",
                parse_mode="Markdown",
            )
            return
        hearing_date = date_arg

    current, _ = _get_room_data(db, room_no)
    vc_links = db.get_vc_zoom_links(_today_ist())

    db.remove_subscription(telegram_id, room_no)
    db.add_subscription(telegram_id, room_no, target_serial, look_ahead, hearing_date=hearing_date)

    alert_at = target_serial - look_ahead
    is_today = hearing_date == _today_ist()
    date_label = "today" if is_today else hearing_date

    lines = [
        f"✅ *Alert set for Room {room_no}*",
        f"Hearing date: *{date_label}*",
        f"Your serial: *{target_serial}*",
        f"You'll be notified when serial reaches *{alert_at}* (i.e., {look_ahead} before yours)",
    ]
    if is_today and current is not None:
        lines.append(f"Current serial: *{current}*")
        if current >= alert_at:
            lines.append("⚠️ _Serial already past alert threshold — you'll get notified on next poll._")
    if is_today and room_no in vc_links:
        lines.append("📹 VC link available for today (sent with alert)")
    elif is_today:
        lines.append("🏛 In-person court (no VC link)")
    lines += ["", "Cancel anytime: `/unwatch " + room_no + "`"]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    args = ctx.args or []

    if not args:
        subs = db.list_user_subscriptions(telegram_id)
        if subs:
            rooms = ", ".join(str(s["room_no"]) for s in subs)
            await update.message.reply_text(
                f"Usage: `/unwatch <room_no>`\n\nYour active rooms: {rooms}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("No active alerts to cancel.")
        return

    room_no = args[0]
    db.remove_subscription(telegram_id, room_no)
    await update.message.reply_text(f"✓ Stopped watching room {room_no}.")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    subs = db.list_user_subscriptions(telegram_id)

    if not subs:
        await update.message.reply_text(
            "No active alerts.\n\nUse /today to see active courts, then `/watch <room> <serial>` to set one.",
            parse_mode="Markdown",
        )
        return

    lines = ["🔔 *Your active alerts:*\n"]
    for s in subs:
        current, _ = _get_room_data(db, str(s["room_no"]))
        current_str = f" (now at {current})" if current is not None else ""
        date_str = s.get("hearing_date") or "any day"
        lines.append(
            f"• *Room {s['room_no']}* — your serial: {s['target_serial']}\n"
            f"  Date: _{date_str}_ · Alert when serial ≥ {s['target_serial'] - s['look_ahead']}{current_str}"
        )
    lines += ["", "Cancel: `/unwatch <room_no>`"]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_TOKEN not set")

    db = _make_db(settings)

    app = Application.builder().token(settings.telegram_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("list", cmd_list))

    log.info("Eventtrace bot starting (polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

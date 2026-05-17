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

import structlog
from datetime import datetime, timezone, timedelta

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ..common.time import ist_today_str
from ..config import Settings
from ..db import get_db

_IST = timezone(timedelta(hours=5, minutes=30))

log = structlog.get_logger()


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


def _make_db(settings: Settings):
    db = get_db(settings)
    db.ensure_schema()
    return db


def _get_room_data(db, room_no: str) -> tuple[int | None, str]:
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


def _all_rooms_summary(db) -> list[dict]:
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


# ── Board state helpers ───────────────────────────────────────────────────────


def _stale_warning(db) -> str:
    last = db.get_monitor_state("last_successful_poll")
    if not last:
        return ""
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
        if age_min > 5:
            return f"\n\n⚠️ _Data is {int(age_min)}m old — monitor may not be running._"
    except Exception:
        pass
    return ""


def _board_closed_msg(db) -> str | None:
    """Return a message if board is closed/not live, else None."""
    board_active = db.get_monitor_state("board_active")
    if board_active != "0":
        return None
    today = ist_today_str()
    now_ist = datetime.now(_IST)
    if now_ist.hour < 10 or (now_ist.hour == 10 and now_ist.minute < 30):
        return f"🏛 Board not live yet for {today}.\nCourt display usually starts at 10:30 AM IST."
    return f"🏛 Board closed for {today}. Court session has ended."


# ── Text-building functions (shared by webhook + polling bot) ─────────────────


_HELP_TEXT = (
    "📋 *SuperSahayak Legal — Court Alerts*\n\n"
    "/today — active courts right now\n"
    "/daily — your alerts + all courts\n"
    "/status `<room>` — current serial for a room\n"
    "/watch `<room> <serial>` — set serial alert\n"
    "/unwatch `<room>` — cancel alert\n"
    "/list — your active alerts\n"
    "/help — show this guide\n\n"
    "Log in at [legal.supersahayak.com](https://legal.supersahayak.com) to manage your account."
)


def build_today(db) -> str:
    vc_links = db.get_vc_zoom_links(ist_today_str())
    rooms = _all_rooms_summary(db)
    stale = _stale_warning(db)
    closed = _board_closed_msg(db)

    if closed:
        return closed + stale

    if not rooms:
        now_ist = datetime.now(_IST)
        if now_ist.hour < 10 or (now_ist.hour == 10 and now_ist.minute < 30):
            msg = f"🏛 Board not live yet for {ist_today_str()}.\nCourt display usually starts at 10:30 AM IST."
        else:
            msg = "📋 No court data available right now.\nMonitor may not be running."
        return msg + stale

    now_ist = datetime.now(_IST).strftime("%d %b, %I:%M %p IST")
    lines = [f"📋 *Active courts — {now_ist}*\n"]
    for r in rooms:
        vc = "📹" if r["room_no"] in vc_links else "🏛"
        judge_short = r["judge"].replace("HON'BLE ", "").replace("JUSTICE ", "").strip()
        if len(judge_short) > 40:
            judge_short = judge_short[:38] + "…"
        serial_str = f"Serial: *{r['serial']}*" if r["serial"] else "Serial: —"
        lines.append(f"{vc} *Room {r['room_no']}* — {serial_str}")
        if judge_short:
            lines.append(f"   _{judge_short}_")
    lines += ["", "📹 = VC available  🏛 = in-person",
              "Use `/status <room>` or `/watch <room> <serial>` to set alert."]
    if stale:
        lines.append(stale)
    return "\n".join(lines)


def build_status(db, args: list[str]) -> str:
    if not args:
        return "Usage: `/status <room_no>`\n\nExample: `/status 8`\n\nUse /today to see all rooms."
    room_no = args[0]
    current, judge = _get_room_data(db, room_no)
    if current is None:
        return (
            f"Room {room_no}: no data.\n"
            "Court may not be in session, or room number is wrong.\n\n"
            "Use /today to see all active rooms."
        )
    vc_links = db.get_vc_zoom_links(ist_today_str())
    lines = [f"🏛 *Room {room_no}*", f"Current serial: *{current}*"]
    if judge:
        judge_clean = judge.replace("HON'BLE ", "").replace("JUSTICE ", "").strip()
        lines.append(f"_{judge_clean}_")
    if room_no in vc_links:
        lines += ["", f"📹 *VC Link:*\n{vc_links[room_no]}"]
    else:
        lines.append("_(In-person court — no VC)_")
    lines += ["", f"Set alert: `/watch {room_no} <your_serial>`"]
    return "\n".join(lines)


def build_watch(db, telegram_id: str, args: list[str]) -> str:
    if len(args) < 2:
        return (
            "Usage: `/watch <room_no> <your_serial> [alert_before] [date]`\n\n"
            "Example: `/watch 8 45` — alert when room 8 reaches serial 40"
        )
    room_no = args[0]
    try:
        target_serial = int(args[1])
        look_ahead = int(args[2]) if len(args) >= 3 else 5
    except ValueError:
        return "Serial and alert\\_before must be numbers.\n\nExample: `/watch 8 45`"
    if look_ahead < 0 or look_ahead > 50:
        return "alert\\_before must be between 0 and 50."

    hearing_date = ist_today_str()
    if len(args) >= 4:
        import re as _re
        date_arg = args[3]
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", date_arg):
            return "Date must be YYYY\\-MM\\-DD format, e.g. `2026-04-25`"
        hearing_date = date_arg

    current, _ = _get_room_data(db, room_no)
    vc_links = db.get_vc_zoom_links(ist_today_str())
    db.remove_subscription(telegram_id, room_no)
    db.add_subscription(telegram_id, room_no, target_serial, look_ahead, hearing_date=hearing_date)

    alert_at = target_serial - look_ahead
    is_today = hearing_date == ist_today_str()
    date_label = "today" if is_today else hearing_date
    lines = [
        f"✅ *Alert set for Room {room_no}*",
        f"Hearing date: *{date_label}*",
        f"Your serial: *{target_serial}*",
        f"You'll be notified when serial reaches *{alert_at}*",
    ]
    if is_today and current is not None:
        lines.append(f"Current serial: *{current}*")
        if current >= alert_at:
            lines.append("⚠️ _Serial already past threshold — alert fires on next poll._")
    if is_today and room_no in vc_links:
        lines.append("📹 VC link available (sent with alert)")
    lines += ["", f"Cancel: `/unwatch {room_no}`"]
    return "\n".join(lines)


def build_unwatch(db, telegram_id: str, args: list[str]) -> str:
    if not args:
        subs = db.list_user_subscriptions(telegram_id)
        if subs:
            rooms = ", ".join(str(s["room_no"]) for s in subs)
            return f"Usage: `/unwatch <room_no>`\n\nYour active rooms: {rooms}"
        return "No active alerts to cancel."
    room_no = args[0]
    db.remove_subscription(telegram_id, room_no)
    return f"✓ Stopped watching room {room_no}."


def build_list(db, telegram_id: str) -> str:
    subs = db.list_user_subscriptions(telegram_id)
    if not subs:
        return "No active alerts.\n\nUse /today to see active courts, then `/watch <room> <serial>` to set one."
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
    return "\n".join(lines)


def build_daily(db, telegram_id: str) -> str:
    today = ist_today_str()
    subs = db.list_user_subscriptions(telegram_id)
    rooms = _all_rooms_summary(db)
    vc_links = db.get_vc_zoom_links(today)
    stale = _stale_warning(db)
    closed = _board_closed_msg(db)
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
            lines.append(f"• *Room {s['room_no']}* — serial {s['target_serial']} · alert at {alert_at}{cur_str}")
            shown += 1
        if shown == 0:
            lines.append("_(none for today)_")
        lines.append("")

    if closed:
        lines.append(closed)
    elif not rooms:
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
    if stale:
        lines.append(stale)
    return "\n".join(lines)


def handle_command(db, telegram_id: str, text: str) -> str | None:
    """Dispatch a bot command. Returns reply text or None if not a known command."""
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].split("@")[0].lower()  # strip @botname suffix
    args = parts[1:]

    if cmd in ("/start", "/help"):
        return _HELP_TEXT
    if cmd == "/today":
        return build_today(db)
    if cmd == "/daily":
        return build_daily(db, telegram_id)
    if cmd == "/status":
        return build_status(db, args)
    if cmd == "/watch":
        return build_watch(db, telegram_id, args)
    if cmd == "/unwatch":
        return build_unwatch(db, telegram_id, args)
    if cmd == "/list":
        return build_list(db, telegram_id)
    return None


# ── Command handlers ─────────────────────────────────────────────────────────


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Deep link from UI: /start watch_<room>_<serial>_<ahead>_<date>
    payload = (ctx.args[0] if ctx.args else "").strip()
    if payload.startswith("watch_"):
        await _handle_deep_link_watch(update, ctx, payload)
        return

    db = ctx.bot_data["db"]
    tg_user = update.effective_user
    chat_id = tg_user.id
    username = (tg_user.username or "").lower()
    first_name = tg_user.first_name or ""
    now_ist = datetime.now(_IST).strftime("%d %b %Y, %I:%M %p IST")

    # Try to link by username if not already linked
    if username:
        try:
            db.set_telegram_chat_id_by_username(username, chat_id)
        except Exception:
            pass

    # Check if linked
    try:
        linked_user = db.get_user_by_telegram_chat_id(chat_id)
    except Exception:
        linked_user = None

    if linked_user:
        name = linked_user.get("name") or first_name or "there"
        text = (
            f"👋 Welcome back, *{name}*\n\n"
            f"✅ Account linked to SuperSahayak Legal\n\n"
            f"*Commands:*\n"
            f"/today — active courts right now\n"
            f"/watch — set serial alert\n"
            f"/daily — your alerts + all courts\n"
            f"/list — your active alerts\n"
            f"/status — current serial for a room\n"
            f"/unwatch — cancel alert\n\n"
            f"🕐 {now_ist}"
        )
    else:
        text = (
            f"👋 Welcome{' ' + first_name if first_name else ''} to SuperSahayak Legal\n\n"
            f"To receive court alerts, link your account:\n\n"
            f"1. Log in at legal.supersahayak.com\n"
            f"2. Go to Settings → Telegram\n"
            f"3. Enter your username: @{username or 'your_username'}\n"
            f"4. Send /start again to confirm\n\n"
            f"Once linked, use /today to see live court data\n\n"
            f"🕐 {now_ist}"
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
        hearing_date = parts[3] if len(parts) >= 4 else ist_today_str()
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid alert link. Use /watch to set an alert manually.")
        return

    db.remove_subscription(telegram_id, room_no)
    db.add_subscription(
        telegram_id,
        room_no,
        target_serial,
        look_ahead,
        hearing_date=hearing_date,
    )
    alert_at = target_serial - look_ahead
    current, _ = _get_room_data(db, room_no)
    vc_links = db.get_vc_zoom_links(ist_today_str())

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
    db = ctx.bot_data["db"]
    await update.message.reply_text(build_today(db), parse_mode="Markdown")


async def cmd_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    await update.message.reply_text(build_daily(db, telegram_id), parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db = ctx.bot_data["db"]
    await update.message.reply_text(build_status(db, ctx.args or []), parse_mode="Markdown")


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    await update.message.reply_text(build_watch(db, telegram_id, ctx.args or []), parse_mode="Markdown")


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    await update.message.reply_text(build_unwatch(db, telegram_id, ctx.args or []), parse_mode="Markdown")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    await update.message.reply_text(build_list(db, telegram_id), parse_mode="Markdown")


# ── Catch-all: redirect to WhatsApp ─────────────────────────────────────────


async def cmd_redirect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "This bot is no longer active.\n\n"
        "Please use *WhatsApp* for court alerts:\n"
        "Send HELP to *+1 415 523 8886* on WhatsApp to get started.",
        parse_mode="Markdown",
    )


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    from ..core.logging_setup import configure_logging

    configure_logging()
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

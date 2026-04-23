"""Telegram bot for @Eventtrace_bot.

Commands:
  /watch <room_no> <serial> [look_ahead]  — subscribe to a room+serial
  /unwatch <room_no>                       — cancel subscription for a room
  /list                                    — show active subscriptions
  /status <room_no>                        — current serial for a room
  /help                                    — usage

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
        f"⚖️ *Court Room {room}* — serial update",
        f"Current serial: *{current}*  |  Your case: *{target}*",
    ]
    if zoom_url:
        lines.append(f"VC link: {zoom_url}")
    else:
        lines.append("VC link: not available (in-person court)")

    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = httpx.post(url, json={"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    resp.raise_for_status()


# ── Command handlers ─────────────────────────────────────────────────────────

def _make_db(settings: Settings) -> DB:
    db = DB(settings.db_path)
    db.ensure_schema()
    return db


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Eventtrace Bot — CHC Display Board Alerts*\n\n"
        "/watch `<room_no> <serial> [look_ahead]`\n"
        "  Alert when serial reaches within `look_ahead` of your case (default 5)\n\n"
        "/unwatch `<room_no>`\n"
        "  Cancel alert for a room\n\n"
        "/list\n"
        "  Show your active alerts\n\n"
        "/status `<room_no>`\n"
        "  Current serial number for a room\n\n"
        "Example: `/watch 8 45 3` — alert when room 8 serial reaches 42"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    args = ctx.args or []

    if len(args) < 2:
        await update.message.reply_text("Usage: /watch <room_no> <serial> [look_ahead]")
        return

    room_no = args[0]
    try:
        target_serial = int(args[1])
        look_ahead = int(args[2]) if len(args) >= 3 else 5
    except ValueError:
        await update.message.reply_text("serial and look_ahead must be integers")
        return

    if look_ahead < 0 or look_ahead > 50:
        await update.message.reply_text("look_ahead must be between 0 and 50")
        return

    db.remove_subscription(telegram_id, room_no)
    sub_id = db.add_subscription(telegram_id, room_no, target_serial, look_ahead)

    vc_links = db.get_vc_zoom_links(_today_ist())
    vc_note = f"\nVC link available for today." if room_no in vc_links else ""

    await update.message.reply_text(
        f"Watching room *{room_no}*, serial *{target_serial}* "
        f"(alert when ≥ {target_serial - look_ahead}, look-ahead {look_ahead}).{vc_note}\n"
        f"Subscription ID: {sub_id}",
        parse_mode="Markdown",
    )


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    args = ctx.args or []

    if not args:
        await update.message.reply_text("Usage: /unwatch <room_no>")
        return

    room_no = args[0]
    db.remove_subscription(telegram_id, room_no)
    await update.message.reply_text(f"Stopped watching room {room_no}.")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    telegram_id = str(update.effective_user.id)
    subs = db.list_user_subscriptions(telegram_id)

    if not subs:
        await update.message.reply_text("No active alerts. Use /watch to add one.")
        return

    lines = ["*Your active alerts:*"]
    for s in subs:
        lines.append(
            f"• Room *{s['room_no']}* — serial {s['target_serial']} "
            f"(alert at {s['target_serial'] - s['look_ahead']}, "
            f"look-ahead {s['look_ahead']})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: DB = ctx.bot_data["db"]
    args = ctx.args or []

    if not args:
        await update.message.reply_text("Usage: /status <room_no>")
        return

    room_no = args[0]
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

    if not serials:
        await update.message.reply_text(f"Room {room_no}: no data (court may not be in session).")
        return

    current = max(serials)
    vc_links = db.get_vc_zoom_links(_today_ist())
    vc_line = f"\nVC: {vc_links[room_no]}" if room_no in vc_links else ""

    msg = f"Room *{room_no}* — current serial: *{current}*"
    if judge:
        msg += f"\n{judge}"
    msg += vc_line
    await update.message.reply_text(msg, parse_mode="Markdown")


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

    app = (
        Application.builder()
        .token(settings.telegram_token)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("status", cmd_status))

    log.info("Eventtrace bot starting (polling)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


"""Central dispatch entry point for the queued notification system.

Call `enqueue_notification(...)` from any trigger site (causelist scanner,
monitor loop, case-diff worker).  It applies all pre-send checks — prefs,
quiet hours, daily cap, dedup — then writes to notification_queue +
notification_log (status=queued).  The retry worker in run_monitor.py
picks it up and does the actual HTTP send.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()

# ── Message builders ──────────────────────────────────────────────────────────

_TRIGGER_TYPES = frozenset([
    "case_in_causelist",
    "serial_reached",
    "display_board_active",
    "hearing_date_changed",
    "order_uploaded",
    "status_changed",
    "judge_changed",
])

# Dedup window hours per trigger type
_DEDUP_HOURS: dict[str, int] = {
    "case_in_causelist": 24,
    "serial_reached": 0,        # no dedup — fast-moving
    "display_board_active": 4,
    "hearing_date_changed": 24,
    "order_uploaded": 24,
    "status_changed": 24,
    "judge_changed": 24,
}


def build_message(trigger_type: str, context: dict) -> str:
    case_ref = context.get("case_ref", "")
    if trigger_type == "case_in_causelist":
        parts = [f"📋 *{case_ref}* listed for {context.get('date', '')}"]
        if context.get("court_no"):
            parts.append(f"Court {context['court_no']}")
        if context.get("section"):
            parts.append(f"Section: {context['section']}")
        if context.get("serial_no"):
            parts.append(f"Serial #{context['serial_no']}")
        if context.get("bench_label"):
            parts.append(f"Bench: {context['bench_label']}")
        if context.get("vc_link"):
            parts.append(f"VC: {context['vc_link']}")
        return "\n".join(parts)

    if trigger_type == "serial_reached":
        return (
            f"⚡ *Case Coming Up!*\n"
            f"Court {context.get('court_no')} board is at serial #{context.get('current_serial')}\n"
            f"Your case {case_ref} is at serial #{context.get('alert_serial')}\n"
            f"Date: {context.get('date', '')}"
        )

    if trigger_type == "display_board_active":
        return (
            f"🟢 *{case_ref}* is now on the live display board\n"
            f"Court {context.get('court_no')} | Serial #{context.get('serial_no', '?')}\n"
            f"Status: {context.get('status', '')}"
        )

    if trigger_type == "hearing_date_changed":
        return (
            f"📅 *Hearing date changed* for {case_ref}\n"
            f"Old: {context.get('old_date', '?')} → New: {context.get('new_date', '?')}"
        )

    if trigger_type == "order_uploaded":
        return (
            f"📄 *New order* uploaded for {case_ref}\n"
            f"Date: {context.get('date', '')}\n"
            f"{context.get('summary', '')}"
        )

    if trigger_type == "status_changed":
        return (
            f"🔄 *Status changed* for {case_ref}\n"
            f"{context.get('old_value', '?')} → {context.get('new_value', '?')}"
        )

    if trigger_type == "judge_changed":
        return (
            f"⚖️ *Judge changed* for {case_ref}\n"
            f"Old: {context.get('old_value', '?')}\n"
            f"New: {context.get('new_value', '?')}"
        )

    return json.dumps({"trigger": trigger_type, **context})


def _make_dedup_key(user_id: str, case_ref: str, trigger_type: str) -> str:
    date_str = datetime.now(timezone.utc).date().isoformat()
    raw = f"{user_id}|{case_ref}|{trigger_type}|{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _in_quiet_hours(pref: dict) -> bool:
    start = pref.get("quiet_hours_start")
    end = pref.get("quiet_hours_end")
    if start is None or end is None:
        return False
    current_hour = datetime.now(timezone.utc).hour + 5  # rough IST
    current_hour %= 24
    if start <= end:
        return start <= current_hour < end
    return current_hour >= start or current_hour < end


# ── Main entry point ──────────────────────────────────────────────────────────


def enqueue_notification(
    db: Any,
    user_id: str,
    case_ref: str,
    trigger_type: str,
    context: dict,
    channel: str | None = None,
) -> bool:
    """
    Pre-flight checks then writes to notification_queue + notification_log.
    Returns True if enqueued, False if skipped/blocked.
    channel: 'whatsapp' | 'email' | None (auto from prefs)
    """
    if trigger_type not in _TRIGGER_TYPES:
        log.warning("enqueue_notification: unknown trigger_type", trigger_type=trigger_type)
        return False

    # Load user
    user = db.get_user_by_id(user_id)
    if not user:
        return False

    # Resolve effective channel(s) to send on
    pref = None
    try:
        pref = db.get_alert_pref(user_id, case_ref, trigger_type)
    except Exception:
        pass

    if pref and not pref.get("enabled", True):
        log.debug("notification skipped: pref disabled", user_id=user_id, trigger=trigger_type)
        return False

    if pref and _in_quiet_hours(pref):
        log.debug("notification skipped: quiet hours", user_id=user_id, trigger=trigger_type)
        return False

    effective_channel = channel or (pref.get("channel") if pref else None) or "whatsapp"

    channels_to_send: list[str] = []
    if effective_channel == "both":
        channels_to_send = ["whatsapp", "email"]
    else:
        channels_to_send = [effective_channel]

    # WhatsApp: require verified number
    if "whatsapp" in channels_to_send:
        if not user.get("whatsapp_verified"):
            wa_number = user.get("whatsapp_number") or user.get("phone")
            if not wa_number:
                channels_to_send = [c for c in channels_to_send if c != "whatsapp"]
            # allow unverified if they have a number (legacy compat)

    # Email: require verified email
    if "email" in channels_to_send:
        if not user.get("email_verified") or not user.get("email"):
            channels_to_send = [c for c in channels_to_send if c != "email"]

    if not channels_to_send:
        log.debug("no valid channels for user", user_id=user_id)
        return False

    message = build_message(trigger_type, {**context, "case_ref": case_ref})
    enqueued = False

    for ch in channels_to_send:
        # Daily cap check (WhatsApp only)
        if ch == "whatsapp":
            cap = user.get("daily_wa_cap", 100)
            try:
                if not db.check_daily_cap(user_id, ch, cap):
                    log.info("daily cap reached", user_id=user_id, channel=ch)
                    continue
            except Exception:
                pass

        # Dedup check
        window_hours = _DEDUP_HOURS.get(trigger_type, 1)
        if window_hours > 0:
            dedup_key = _make_dedup_key(user_id, case_ref, trigger_type)
            try:
                if not db.check_dedup(dedup_key, window_hours):
                    log.debug("dedup skip", user_id=user_id, trigger=trigger_type)
                    continue
            except Exception:
                dedup_key = None
        else:
            dedup_key = None

        # Write log row (status=queued)
        try:
            log_id = db.create_notification_log(
                user_id=user_id,
                case_ref=case_ref,
                notification_type=trigger_type,
                channel=ch,
                message_text=message,
                status="queued",
                dedup_key=dedup_key,
            )
        except Exception as exc:
            log.warning("create_notification_log failed", exc=str(exc))
            continue

        # Write queue row
        payload = json.dumps({"trigger_type": trigger_type, "channel": ch, **context, "case_ref": case_ref})
        try:
            db.enqueue_notification(
                user_id=user_id,
                case_ref=case_ref,
                notification_type=trigger_type,
                channel=ch,
                payload_json=payload,
                notification_log_id=log_id,
            )
            enqueued = True
        except Exception as exc:
            log.warning("enqueue_notification failed", exc=str(exc))
            try:
                db.update_notification_status(log_id, "failed")
            except Exception:
                pass

    return enqueued

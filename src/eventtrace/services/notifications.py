"""Notification delivery: WhatsApp (WATI / MSG91) + Email (Resend)."""

from __future__ import annotations

import json
import structlog
import os
from typing import Any

log = structlog.get_logger()


def _wati_key() -> str:
    return os.getenv("WATI_API_KEY", "")


def _msg91_whatsapp_key() -> str:
    return os.getenv("MSG91_WHATSAPP_KEY", "") or os.getenv("MSG91_AUTH_KEY", "")


def _resend_key() -> str:
    return os.getenv("RESEND_API_KEY", "")


def _resend_from() -> str:
    return os.getenv("RESEND_FROM_EMAIL", "alerts@supersahayak.in")


def _msg91_whatsapp_number() -> str:
    return os.getenv("MSG91_WHATSAPP_NUMBER", "")


# ── Message formatters ────────────────────────────────────────────────────────


def _format_message(alert_type: str, context: dict) -> str:
    if alert_type == "serial_reached":
        return (
            f"⚡ Case Coming Up Soon!\n"
            f"Court {context.get('court_no')} display board is at serial #{context.get('current_serial')}\n"
            f"Your case {context.get('case_ref')} is at serial #{context.get('alert_serial')}\n"
            f"Cause list date: {context.get('date', '')}"
        )
    if alert_type == "case_in_causelist":
        parts = [
            f"📋 Your case {context.get('case_ref')} is listed for {context.get('date')}",
            f"Court {context.get('court_no')} | Section: {context.get('section', '')}",
        ]
        if context.get("serial_no"):
            parts.append(f"Serial #{context.get('serial_no')}")
        if context.get("bench_label"):
            parts.append(f"Bench: {context.get('bench_label')}")
        if context.get("vc_link"):
            parts.append(f"VC Link: {context.get('vc_link')}")
        return "\n".join(parts)
    if alert_type == "case_updated":
        summary = context.get("summary", "fields changed")
        return f"🔔 Update detected in {context.get('case_ref')}: {summary}."
    return json.dumps(context)


# ── WhatsApp delivery ─────────────────────────────────────────────────────────


def _send_wati(phone: str, message: str, wati_key: str) -> bool:
    try:
        import httpx

        # Strip non-digits, WATI expects number without '+'
        number = phone.lstrip("+")
        resp = httpx.post(
            "https://live-mt-server.wati.io/api/v1/sendTemplateMessage",
            headers={"Authorization": f"Bearer {wati_key}", "Content-Type": "application/json"},
            json={
                "whatsappNumber": number,
                "templateName": "hearing_alert",
                "parameters": [{"name": "message", "value": message}],
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("WATI error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("WATI send failed: %s", exc)
        return False


def _send_msg91_whatsapp(phone: str, message: str, auth_key: str) -> bool:
    wa_number = _msg91_whatsapp_number()
    if not wa_number:
        log.warning("MSG91_WHATSAPP_NUMBER not set — skipping MSG91 WhatsApp")
        return False
    try:
        import httpx

        mobile = phone.lstrip("+")
        resp = httpx.post(
            "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/",
            headers={"authkey": auth_key, "Content-Type": "application/json"},
            json={
                "integrated_number": wa_number,
                "content_type": "template",
                "payload": {
                    "messaging_product": "whatsapp",
                    "type": "template",
                    "template": {
                        "name": "hearing_alert",
                        "language": {"code": "en"},
                        "components": [
                            {
                                "type": "body",
                                "parameters": [{"type": "text", "text": message}],
                            }
                        ],
                    },
                    "to": mobile,
                },
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("MSG91 WhatsApp error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("MSG91 WhatsApp send failed: %s", exc)
        return False


# ── Email delivery (Resend) ───────────────────────────────────────────────────


def send_email_alert(to_email: str, subject: str, body_html: str) -> bool:
    api_key = _resend_key()
    if not api_key:
        log.info("RESEND_API_KEY not set — skipping email to %s", to_email)
        return False
    try:
        import httpx

        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": _resend_from(),
                "to": [to_email],
                "subject": subject,
                "html": body_html,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("Resend error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("Resend email failed: %s", exc)
        return False


# ── Main send_alert ───────────────────────────────────────────────────────────


def send_alert(
    db: Any,
    tracked_case: dict,
    alert_type: str,
    context: dict,
) -> None:
    user_id = tracked_case.get("user_id", "")
    case_ref = tracked_case.get("case_ref", "")
    tracked_case_id = tracked_case.get("id")

    user = db.get_user_by_id(str(user_id)) if user_id else None
    if not user:
        log.warning("send_alert: user %s not found for case %s", user_id, case_ref)
        return

    prefs: dict = {}
    try:
        prefs = db.get_notification_prefs(str(user_id))
    except Exception:
        pass

    message = _format_message(alert_type, {**context, "case_ref": case_ref})
    payload = json.dumps({"alert_type": alert_type, "case_ref": case_ref, **context})

    wa_sent = False
    phone = user.get("phone", "")

    if phone and prefs.get("whatsapp", True):
        wati_key = _wati_key()
        if wati_key:
            wa_sent = _send_wati(phone, message, wati_key)
        if not wa_sent:
            msg91_key = _msg91_whatsapp_key()
            if msg91_key:
                wa_sent = _send_msg91_whatsapp(phone, message, msg91_key)

        if not wa_sent and not wati_key and not _msg91_whatsapp_key():
            log.info("No WhatsApp provider configured — queuing notification as pending_approval")
            status = "pending_approval"
        else:
            status = "sent" if wa_sent else "failed"
    else:
        status = "skipped"

    try:
        if tracked_case_id:
            db.log_case_notification(tracked_case_id, payload, status)
    except Exception as exc:
        log.warning("log_case_notification failed: %s", exc)

    email = user.get("email", "")
    if email and user.get("email_verified") and prefs.get("email", True):
        subject = _email_subject(alert_type, context, case_ref)
        body_html = f"<p>{message}</p>"
        send_email_alert(email, subject, body_html)


def _email_subject(alert_type: str, context: dict, case_ref: str) -> str:
    if alert_type == "serial_reached":
        return f"[SuperSahayak Legal] Court {context.get('court_no')} — Serial Alert for {case_ref}"
    if alert_type == "case_in_causelist":
        return f"[SuperSahayak Legal] {case_ref} listed for {context.get('date', '')}"
    return f"[SuperSahayak Legal] Update for {case_ref}"

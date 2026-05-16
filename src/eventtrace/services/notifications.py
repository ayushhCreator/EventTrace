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
    return os.getenv("RESEND_FROM_EMAIL", "alerts@legal.supersahayak.com")


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


_MSG91_WA_NAMESPACE = "1bdf9737_865c_42a5_8c80_aa36de3fa847"
_MSG91_WA_TEMPLATE = "court_update"
_MSG91_WA_WELCOME_TEMPLATE = os.getenv("MSG91_WA_TEMPLATE_WELCOME", "ss_welcome")


def _send_msg91_whatsapp(phone: str, message: str, auth_key: str) -> bool:
    wa_number = _msg91_whatsapp_number()
    if not wa_number:
        log.warning("MSG91_WHATSAPP_NUMBER not set — skipping MSG91 WhatsApp")
        return False
    try:
        import httpx

        mobile = phone.lstrip("+")
        if os.getenv("MSG91_DRY_RUN"):
            log.warning("[DRY-RUN] MSG91 WhatsApp → to=%s integrated=%s template=%s body=%r", mobile, wa_number, _MSG91_WA_TEMPLATE, message)
            return True
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
                        "name": _MSG91_WA_TEMPLATE,
                        "language": {"code": "en", "policy": "deterministic"},
                        "namespace": _MSG91_WA_NAMESPACE,
                        "to_and_components": [
                            {
                                "to": [mobile],
                                "components": {
                                    "body_1": {"type": "text", "value": message}
                                },
                            }
                        ],
                    },
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


def send_welcome_whatsapp(phone: str, name: str) -> bool:
    """Send welcome template to new user on first login."""
    auth_key = _msg91_whatsapp_key()
    wa_number = _msg91_whatsapp_number()
    if not auth_key or not wa_number:
        log.info("MSG91 not configured — skipping welcome WhatsApp to %s", phone)
        return False
    try:
        import httpx

        mobile = phone.lstrip("+")
        display_name = name or "there"
        if os.getenv("MSG91_DRY_RUN"):
            log.warning("[DRY-RUN] welcome WhatsApp → to=%s name=%r template=%s", mobile, display_name, _MSG91_WA_WELCOME_TEMPLATE)
            return True
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
                        "name": _MSG91_WA_WELCOME_TEMPLATE,
                        "language": {"code": "en", "policy": "deterministic"},
                        "namespace": _MSG91_WA_NAMESPACE,
                        "to_and_components": [
                            {
                                "to": [mobile],
                                "components": {
                                    "body_1": {"type": "text", "value": display_name}
                                },
                            }
                        ],
                    },
                },
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("Welcome WhatsApp error %s: %s", resp.status_code, resp.text[:200])
            return False
        log.info("Welcome WhatsApp sent to %s", mobile)
        return True
    except Exception as exc:
        log.warning("Welcome WhatsApp send failed: %s", exc)
        return False


def send_msg91_session_message(phone: str, text: str, auth_key: str) -> bool:
    """Send a free-form session message (within 24h of user's inbound message)."""
    wa_number = _msg91_whatsapp_number()
    if not wa_number:
        log.warning("MSG91_WHATSAPP_NUMBER not set — skipping session message")
        return False
    try:
        import httpx

        mobile = phone.lstrip("+")
        resp = httpx.post(
            "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/",
            headers={"authkey": auth_key, "Content-Type": "application/json"},
            json={
                "integrated_number": wa_number,
                "content_type": "text",
                "payload": {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": mobile,
                    "type": "text",
                    "text": {"body": text},
                },
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("MSG91 session msg error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("MSG91 session msg failed: %s", exc)
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
    whatsapp_number = user.get("whatsapp_number") or phone

    if whatsapp_number and prefs.get("whatsapp", True):
        wati_key = _wati_key()
        if wati_key:
            wa_sent = _send_wati(whatsapp_number, message, wati_key)
        if not wa_sent:
            msg91_key = _msg91_whatsapp_key()
            if msg91_key:
                wa_sent = _send_msg91_whatsapp(whatsapp_number, message, msg91_key)

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
        body_html = build_email_html(alert_type, {**context, "case_ref": case_ref}, case_ref)
        send_email_alert(email, subject, body_html)


def _email_subject(alert_type: str, context: dict, case_ref: str) -> str:
    if alert_type == "serial_reached":
        ref = case_ref or f"serial {context.get('target_serial', '')}"
        return f"SuperSahayak Legal — Court {context.get('court_no')} approaching: {ref}"
    if alert_type == "case_in_causelist":
        date = context.get("date", "")
        court = context.get("court_no", "")
        court_str = f"Court {court} — " if court else ""
        return f"SuperSahayak Legal — {court_str}{case_ref} listed for {date}"
    if alert_type == "display_board_active":
        return f"SuperSahayak Legal — {case_ref} is on the live display board"
    if alert_type == "hearing_date_changed":
        return f"SuperSahayak Legal — Hearing date changed for {case_ref}"
    if alert_type == "vc_link_available":
        return f"SuperSahayak Legal — VC link ready for {case_ref}"
    if alert_type == "causelist_released":
        return "SuperSahayak Legal — Tomorrow's cause list is out"
    return f"SuperSahayak Legal — Update for {case_ref}"


_EMAIL_WRAPPER = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;max-width:600px;width:100%%;">
  <tr><td style="background:#1a1a2e;padding:20px 32px;">
    <span style="color:#ffffff;font-size:18px;font-weight:bold;letter-spacing:0.5px;">SuperSahayak Legal</span>
  </td></tr>
  <tr><td style="padding:32px;">
    {body}
  </td></tr>
  <tr><td style="background:#f8f8f8;padding:16px 32px;border-top:1px solid #e8e8e8;">
    <p style="margin:0;font-size:12px;color:#888;">You're receiving this because you track cases on SuperSahayak Legal.</p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _kv_row(label: str, value: str) -> str:
    return (
        f'<tr><td style="padding:4px 0;color:#666;font-size:13px;width:130px;vertical-align:top;">{label}</td>'
        f'<td style="padding:4px 0;color:#1a1a2e;font-size:13px;font-weight:600;">{value}</td></tr>'
    )


def build_email_html(trigger_type: str, context: dict, case_ref: str) -> str:
    if trigger_type == "case_in_causelist":
        date = context.get("date", "")
        court = context.get("court_no", "")
        serial = context.get("serial_no", "")
        bench = context.get("bench_label", "")
        section = context.get("section", "")
        vc_link = context.get("vc_link", "")

        rows = ""
        if court:
            rows += _kv_row("Court", str(court))
        if serial:
            rows += _kv_row("Serial #", str(serial))
        if bench:
            rows += _kv_row("Bench", bench)
        if section:
            rows += _kv_row("Section", section)
        if date:
            rows += _kv_row("Hearing date", date)

        vc_html = ""
        if vc_link:
            vc_html = (
                f'<p style="margin:20px 0 0;"><a href="{vc_link}" '
                f'style="background:#1a1a2e;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;font-size:14px;">Join VC</a></p>'
            )

        body = (
            f'<h2 style="margin:0 0 8px;color:#1a1a2e;font-size:20px;">📋 Case Listed</h2>'
            f'<p style="margin:0 0 20px;color:#444;font-size:15px;">'
            f'<strong>{case_ref}</strong> is listed for hearing on <strong>{date}</strong>.</p>'
            f'<table cellpadding="0" cellspacing="0" style="width:100%;border-top:1px solid #e8e8e8;padding-top:16px;">'
            f'{rows}</table>{vc_html}'
        )

    elif trigger_type == "serial_reached":
        court = context.get("court_no", "")
        current = context.get("current_serial", "")
        target = context.get("target_serial", "")
        date = context.get("date", "")
        petitioner = context.get("petitioner", "")
        respondent = context.get("respondent", "")
        advocate = context.get("advocate", "")
        bench_label = context.get("bench_label", "")
        vc_link = context.get("vc_link", "")
        judges_json = context.get("judges_json", "[]")
        try:
            judges = json.loads(judges_json) if judges_json else []
        except Exception:
            judges = []
        judges_str = ", ".join(judges) if judges else ""

        rows = _kv_row("Court", str(court)) if court else ""
        rows += _kv_row("Board now at serial", str(current)) if current else ""
        rows += _kv_row("Your case serial", str(target)) if target else ""
        if case_ref:
            rows += _kv_row("Case number", case_ref)
        if petitioner or respondent:
            parties = " vs. ".join(filter(None, [petitioner, respondent]))
            rows += _kv_row("Parties", parties)
        if advocate:
            rows += _kv_row("Advocate", advocate)
        if bench_label:
            rows += _kv_row("Bench", bench_label)
        if judges_str:
            rows += _kv_row("Judge(s)", judges_str)
        if date:
            rows += _kv_row("Date", date)

        vc_html = ""
        if vc_link:
            vc_html = (
                f'<p style="margin:20px 0 0;">'
                f'<a href="{vc_link}" style="background:#1a1a2e;color:#fff;padding:10px 20px;'
                f'border-radius:4px;text-decoration:none;font-size:14px;">🎥 Join VC Link</a></p>'
            )

        display_ref = case_ref or f"Serial {target}"
        body = (
            f'<h2 style="margin:0 0 8px;color:#b45309;font-size:20px;">⚡ Case Coming Up Soon</h2>'
            f'<p style="margin:0 0 20px;color:#444;font-size:15px;">'
            f'<strong>{display_ref}</strong> is approaching on the display board.</p>'
            f'<table cellpadding="0" cellspacing="0" style="width:100%;border-top:1px solid #e8e8e8;padding-top:16px;">'
            f'{rows}</table>{vc_html}'
        )

    elif trigger_type == "display_board_active":
        court = context.get("court_no", "")
        serial = context.get("serial_no", "")
        status = context.get("status", "")
        rows = _kv_row("Court", str(court)) if court else ""
        rows += _kv_row("Serial #", str(serial)) if serial else ""
        rows += _kv_row("Status", status) if status else ""
        body = (
            f'<h2 style="margin:0 0 8px;color:#16a34a;font-size:20px;">🟢 On Live Display Board</h2>'
            f'<p style="margin:0 0 20px;color:#444;font-size:15px;">'
            f'<strong>{case_ref}</strong> has appeared on the live court display board.</p>'
            f'<table cellpadding="0" cellspacing="0" style="width:100%;border-top:1px solid #e8e8e8;padding-top:16px;">'
            f'{rows}</table>'
        )

    elif trigger_type == "hearing_date_changed":
        old_date = context.get("old_date", "?")
        new_date = context.get("new_date", "?")
        body = (
            f'<h2 style="margin:0 0 8px;color:#7c3aed;font-size:20px;">📅 Hearing Date Changed</h2>'
            f'<p style="margin:0 0 20px;color:#444;font-size:15px;">'
            f'The next hearing date for <strong>{case_ref}</strong> has changed.</p>'
            f'<table cellpadding="0" cellspacing="0" style="width:100%;border-top:1px solid #e8e8e8;padding-top:16px;">'
            f'{_kv_row("Old date", old_date)}'
            f'{_kv_row("New date", f"<strong>{new_date}</strong>")}'
            f'</table>'
        )

    elif trigger_type == "vc_link_available":
        vc_link = context.get("vc_link", "")
        court = context.get("court_no", "")
        date = context.get("date", "")
        rows = _kv_row("Court", str(court)) if court else ""
        rows += _kv_row("Date", date) if date else ""
        vc_html = ""
        if vc_link:
            vc_html = (
                f'<p style="margin:20px 0 0;"><a href="{vc_link}" '
                f'style="background:#1a1a2e;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;font-size:14px;">Join VC</a></p>'
            )
        body = (
            f'<h2 style="margin:0 0 8px;color:#0369a1;font-size:20px;">🔗 VC Link Ready</h2>'
            f'<p style="margin:0 0 20px;color:#444;font-size:15px;">'
            f'A video conferencing link is now available for <strong>{case_ref}</strong>.</p>'
            f'<table cellpadding="0" cellspacing="0" style="width:100%;border-top:1px solid #e8e8e8;padding-top:16px;">'
            f'{rows}</table>{vc_html}'
        )

    else:
        # Generic fallback
        from .notification_dispatch import build_message
        plain = build_message(trigger_type, {**context, "case_ref": case_ref})
        lines = plain.replace("\n", "<br>")
        body = (
            f'<h2 style="margin:0 0 16px;color:#1a1a2e;font-size:18px;">Update for {case_ref}</h2>'
            f'<p style="color:#444;font-size:14px;line-height:1.6;">{lines}</p>'
        )

    return _EMAIL_WRAPPER.format(body=body)

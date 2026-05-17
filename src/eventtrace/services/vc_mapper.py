"""VC link mapper — confidence scoring, delivery logging, stale link alerts.

Matching logic (spec §MODULE 1):
  composite_key = (court_id, bench_id, hearing_date)
  All 3 match → HIGH   → auto-approve, send link
  Any 2 match → MEDIUM → flag for admin review, hold VC link
  Any 1 match → LOW    → do not use at all

A VC link is only sent when:
  verified = True AND last_verified_at within 7 days of today.

Stale / unverified → admin alert + notification WITHOUT vc_link.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from .admin_alerts import create_admin_alert

log = structlog.get_logger()

_STALE_DAYS = 7


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _score_confidence(
    court_id: str,
    bench_id: str,
    hearing_date: str,
    vc: dict,
) -> str:
    """Return HIGH / MEDIUM / LOW based on how many fields match.

    vc dict keys: court_id, bench_id, hearing_date (from VcLink row).
    hearing_date on VcLink may be absent (None).
    """
    matches = 0
    if vc.get("court_id") == court_id:
        matches += 1
    if vc.get("bench_id") == bench_id:
        matches += 1
    if vc.get("hearing_date") and vc.get("hearing_date") == hearing_date:
        matches += 1
    elif not vc.get("hearing_date") and hearing_date:
        # VcLink doesn't carry a hearing_date — treat bench-level links as 2-field
        pass

    if matches >= 3:
        return "HIGH"
    if matches >= 2:
        return "MEDIUM"
    return "LOW"


def _is_stale(vc: dict) -> bool:
    """True if not verified OR last_verified_at is > STALE_DAYS ago."""
    if not vc.get("verified"):
        return True
    last_verified = vc.get("last_verified_at")
    if not last_verified:
        return True
    try:
        lv = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
        return (_now_utc() - lv) > timedelta(days=_STALE_DAYS)
    except Exception:
        return True


def resolve_vc_link(
    db: Any,
    court_id: str,
    bench_id: str,
    hearing_date: str,
    case_number: str,
    notification_id: str | None = None,
) -> dict:
    """Resolve the best VC link for a hearing and log the delivery attempt.

    Returns:
        {
          "vc_link": str | None,
          "confidence": "HIGH" | "MEDIUM" | "LOW" | None,
          "message": str,        # human-readable status
          "delivery_log_id": str,
        }
    vc_link is None if confidence < HIGH or link is stale/unverified.
    """
    vc_row = None
    try:
        vc_row = db.get_vc_link(court_id, bench_id)
    except Exception as exc:
        log.warning("vc_mapper: db.get_vc_link failed", exc=str(exc))

    delivery_log_id = str(uuid.uuid4())
    now = _now_utc().isoformat()

    if vc_row is None:
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, "LOW", now)
        return {
            "vc_link": None,
            "confidence": "LOW",
            "message": "VC link pending verification — check court notice board",
            "delivery_log_id": delivery_log_id,
        }

    confidence = _score_confidence(court_id, bench_id, hearing_date, vc_row)
    stale = _is_stale(vc_row)

    if stale:
        _fire_stale_alert(db, court_id, bench_id, vc_row)

    if confidence == "LOW":
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, confidence, now)
        return {
            "vc_link": None,
            "confidence": confidence,
            "message": "VC link confidence too low — not sent",
            "delivery_log_id": delivery_log_id,
        }

    if confidence == "MEDIUM":
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, confidence, now)
        return {
            "vc_link": None,
            "confidence": confidence,
            "message": "VC link flagged for admin review — not sent automatically",
            "delivery_log_id": delivery_log_id,
        }

    # HIGH confidence
    if stale:
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, confidence, now)
        return {
            "vc_link": None,
            "confidence": confidence,
            "message": "VC link pending verification — check court notice board",
            "delivery_log_id": delivery_log_id,
        }

    vc_link_sent = vc_row.get("vc_link")
    _log_delivery(db, delivery_log_id, notification_id, case_number, vc_link_sent, court_id, bench_id, confidence, now)
    log.info(
        "vc_mapper: link resolved",
        court_id=court_id, bench_id=bench_id, confidence=confidence, case_number=case_number,
    )
    return {
        "vc_link": vc_link_sent,
        "confidence": confidence,
        "message": "VC link sent",
        "delivery_log_id": delivery_log_id,
    }


def _log_delivery(
    db: Any,
    delivery_log_id: str,
    notification_id: str | None,
    case_number: str,
    vc_link_sent: str | None,
    court_id: str,
    bench_id: str,
    confidence: str,
    now: str,
) -> None:
    try:
        db.create_vc_delivery_log(
            id=delivery_log_id,
            notification_id=notification_id,
            case_number=case_number,
            vc_link_sent=vc_link_sent,
            matched_court_id=court_id,
            matched_bench=bench_id,
            confidence=confidence,
            delivered_at=now,
        )
    except Exception as exc:
        log.warning("vc_mapper: delivery log write failed", exc=str(exc))


def _fire_stale_alert(db: Any, court_id: str, bench_id: str, vc_row: dict) -> None:
    msg = (
        f"Court {court_id} / Bench {bench_id} has a stale or unverified VC link.\n"
        f"Last verified: {vc_row.get('last_verified_at', 'never')}\n"
        f"Link: {vc_row.get('vc_link', 'N/A')}"
    )
    create_admin_alert(
        db,
        alert_type="STALE_VC_LINK",
        message=msg,
        severity="WARNING",
        metadata={"court_id": court_id, "bench_id": bench_id},
    )

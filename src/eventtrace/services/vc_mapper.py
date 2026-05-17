"""VC link mapper — confidence scoring, delivery logging, stale link alerts.

Matching logic (spec §MODULE 1):
  Match on (court_id, bench_id, hearing_date):
    3/3 → HIGH   → auto-approve, send link
    2/3 → MEDIUM → flag for admin review, hold VC link
    1/3 → LOW    → do not use at all

A VC link is only sent when verified=True AND last_verified_at within 7 days.

SOLID:
  - Single Responsibility: pure confidence scoring in _score_confidence(),
    delivery logging in _log_delivery(), alert in _fire_stale_alert().
  - Dependency Inversion: db: Any — works with any backend.
DRY: _build_result() builds all response dicts from one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from .admin_alerts import create_admin_alert

log = structlog.get_logger()

_STALE_DAYS = 7


# ── Pure functions (no I/O — fully testable) ──────────────────────────────────


def score_confidence(
    court_id: str,
    bench_id: str,
    hearing_date: str,
    vc: dict,
) -> str:
    """Return HIGH / MEDIUM / LOW.

    VcLink may omit hearing_date (bench-level links).
    In that case only court_id + bench_id can match → max MEDIUM.
    """
    matches = 0
    if (vc.get("court_id") or "").strip() == court_id.strip():
        matches += 1
    if (vc.get("bench_id") or "").strip() == bench_id.strip():
        matches += 1
    vc_date = vc.get("hearing_date") or ""
    if vc_date and vc_date.strip() == hearing_date.strip():
        matches += 1

    if matches >= 3:
        return "HIGH"
    if matches >= 2:
        return "MEDIUM"
    return "LOW"


def is_stale(vc: dict) -> bool:
    """True if not verified OR last_verified_at is older than STALE_DAYS."""
    if not vc.get("verified"):
        return True
    raw = vc.get("last_verified_at")
    if not raw:
        return True
    try:
        lv = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - lv) > timedelta(days=_STALE_DAYS)
    except Exception:
        return True


# ── Result builder (DRY) ──────────────────────────────────────────────────────


def _build_result(
    vc_link: str | None,
    confidence: str,
    message: str,
    delivery_log_id: str,
) -> dict:
    return {
        "vc_link": vc_link,
        "confidence": confidence,
        "message": message,
        "delivery_log_id": delivery_log_id,
    }


# ── I/O helpers ───────────────────────────────────────────────────────────────


def _log_delivery(
    db: Any,
    delivery_log_id: str,
    notification_id: str | None,
    case_number: str,
    vc_link_sent: str | None,
    court_id: str,
    bench_id: str,
    confidence: str,
    source_court: str,
    now: str,
) -> None:
    try:
        db.create_vc_delivery_log(
            id=delivery_log_id,
            source_court=source_court,
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


def _fire_stale_alert(db: Any, court_id: str, bench_id: str, vc_row: dict, source_court: str) -> None:
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
        source_court=source_court,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def resolve_vc_link(
    db: Any,
    court_id: str,
    bench_id: str,
    hearing_date: str,
    case_number: str,
    notification_id: str | None = None,
    source_court: str = "CHD",
) -> dict:
    """Resolve the best VC link for a hearing and log the delivery attempt.

    Returns:
        {"vc_link": str|None, "confidence": str|None, "message": str, "delivery_log_id": str}
    vc_link is None when confidence < HIGH or link is stale/unverified.
    """
    vc_row = None
    try:
        vc_row = db.get_vc_link(court_id, bench_id)
    except Exception as exc:
        log.warning("vc_mapper: db.get_vc_link failed", exc=str(exc))

    delivery_log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    if vc_row is None:
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, "LOW", source_court, now)
        return _build_result(None, "LOW", "VC link pending verification — check court notice board", delivery_log_id)

    confidence = score_confidence(court_id, bench_id, hearing_date, vc_row)
    stale = is_stale(vc_row)

    if stale:
        _fire_stale_alert(db, court_id, bench_id, vc_row, source_court)

    if confidence == "LOW":
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, confidence, source_court, now)
        return _build_result(None, confidence, "VC link confidence too low — not sent", delivery_log_id)

    if confidence == "MEDIUM":
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, confidence, source_court, now)
        return _build_result(None, confidence, "VC link flagged for admin review — not sent automatically", delivery_log_id)

    # HIGH confidence path
    if stale:
        _log_delivery(db, delivery_log_id, notification_id, case_number, None, court_id, bench_id, confidence, source_court, now)
        return _build_result(None, confidence, "VC link pending verification — check court notice board", delivery_log_id)

    vc_link_sent = vc_row.get("vc_link")
    _log_delivery(db, delivery_log_id, notification_id, case_number, vc_link_sent, court_id, bench_id, confidence, source_court, now)
    log.info("vc_mapper: link resolved", court_id=court_id, bench_id=bench_id, confidence=confidence, case_number=case_number)
    return _build_result(vc_link_sent, confidence, "VC link sent", delivery_log_id)

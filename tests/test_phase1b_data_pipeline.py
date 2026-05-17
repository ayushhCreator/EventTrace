"""Phase 1B data pipeline tests.

Run: pytest tests/test_phase1b_data_pipeline.py -v

Proof criteria:
- VC confidence HIGH on all three match
- VC confidence MEDIUM on two match
- VC confidence LOW on one match
- Stale VC link triggers admin alert
- Scraper guard respects domain rate limit (Redis NX key)
- Scraper guard records 429 and fires alert at threshold
- Reconciliation creates a result row on HIGH/MEDIUM match
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── VC Mapper ─────────────────────────────────────────────────────────────────


class _FakeDB:
    """Minimal in-memory stub for DB methods used by Phase 1B services."""

    def __init__(self):
        self._vc = None
        self._delivery_logs: list[dict] = []
        self._admin_alerts: list[dict] = []
        self._recon_results: list[dict] = []

    def get_vc_link(self, court_id, bench_id):
        return self._vc

    def create_vc_delivery_log(self, **kwargs):
        self._delivery_logs.append(kwargs)

    def create_admin_alert(self, **kwargs):
        self._admin_alerts.append(kwargs)

    def create_reconciliation_result(self, **kwargs):
        self._recon_results.append(kwargs)


def _make_vc(court_id="C1", bench_id="B1", verified=True, days_since_verify=0, vc_link="https://zoom.us/test"):
    last_verified = (datetime.now(timezone.utc) - timedelta(days=days_since_verify)).isoformat()
    return {
        "court_id": court_id,
        "bench_id": bench_id,
        "vc_link": vc_link,
        "verified": 1 if verified else 0,
        "last_verified_at": last_verified if verified else None,
        "hearing_date": None,
    }


def test_vc_confidence_high_on_all_three_match():
    """HIGH when court_id + bench_id + hearing_date all match."""
    from eventtrace.services.vc_mapper import _score_confidence

    vc = {"court_id": "C1", "bench_id": "B1", "hearing_date": "2026-05-17"}
    assert _score_confidence("C1", "B1", "2026-05-17", vc) == "HIGH"


def test_vc_confidence_medium_on_two_match():
    """MEDIUM when court_id + bench_id match but hearing_date absent on vc row."""
    from eventtrace.services.vc_mapper import _score_confidence

    vc = {"court_id": "C1", "bench_id": "B1", "hearing_date": None}
    # Only court_id and bench_id match (2 fields)
    result = _score_confidence("C1", "B1", "2026-05-17", vc)
    assert result == "MEDIUM"


def test_vc_confidence_low_on_one_match():
    """LOW when only court_id matches."""
    from eventtrace.services.vc_mapper import _score_confidence

    vc = {"court_id": "C1", "bench_id": "WRONG", "hearing_date": "2000-01-01"}
    assert _score_confidence("C1", "B1", "2026-05-17", vc) == "LOW"


def test_stale_vc_link_triggers_admin_alert():
    """resolve_vc_link fires admin alert when link is stale (>7 days unverified)."""
    db = _FakeDB()
    db._vc = _make_vc(court_id="C1", bench_id="B1", verified=True, days_since_verify=10)

    with patch("eventtrace.services.admin_alerts._send_telegram", return_value=True):
        from eventtrace.services.vc_mapper import resolve_vc_link
        result = resolve_vc_link(db, "C1", "B1", "2026-05-17", "CW/1234/2026")

    # Alert was created
    assert len(db._admin_alerts) >= 1
    alert_types = [a["alert_type"] for a in db._admin_alerts]
    assert "STALE_VC_LINK" in alert_types

    # Stale link not sent even if HIGH confidence
    assert result["vc_link"] is None


def test_fresh_verified_high_confidence_sends_link():
    """resolve_vc_link returns vc_link when HIGH confidence + fresh + verified."""
    db = _FakeDB()
    db._vc = _make_vc(court_id="C1", bench_id="B1", verified=True, days_since_verify=0)
    db._vc["hearing_date"] = "2026-05-17"

    from eventtrace.services.vc_mapper import resolve_vc_link
    result = resolve_vc_link(db, "C1", "B1", "2026-05-17", "CW/1234/2026")

    assert result["vc_link"] == "https://zoom.us/test"
    assert result["confidence"] == "HIGH"
    # Delivery log written
    assert len(db._delivery_logs) == 1


# ── Scraper Guard ─────────────────────────────────────────────────────────────


def test_scraper_respects_rate_limit():
    """acquire() returns False when Redis key already set (rate limited)."""
    from eventtrace.services.scraper_guard import ScraperGuard

    mock_redis = MagicMock()
    # First call: key set successfully (allowed)
    mock_redis.set.return_value = True
    guard = ScraperGuard(mock_redis)
    assert guard.acquire("example.com") is True

    # Second call: key already exists (NX returns None)
    mock_redis.set.return_value = None
    assert guard.acquire("example.com") is False


def test_scraper_backs_off_on_429():
    """record_429 increments counter; at threshold fires admin alert."""
    db = _FakeDB()

    mock_redis = MagicMock()
    # Simulate incr returning the threshold value
    mock_redis.incr.return_value = 3
    mock_redis.expire.return_value = True

    with patch("eventtrace.services.admin_alerts._send_telegram", return_value=True):
        from eventtrace.services.scraper_guard import ScraperGuard, _MAX_CONSECUTIVE_429S
        guard = ScraperGuard(mock_redis)
        count = guard.record_429("ecourts.gov.in", db)

    assert count == _MAX_CONSECUTIVE_429S
    assert len(db._admin_alerts) >= 1
    assert db._admin_alerts[0]["alert_type"] == "SCRAPER_BANNED"


def test_scraper_guard_no_redis_fails_open():
    """ScraperGuard with None redis always returns True (fail open)."""
    from eventtrace.services.scraper_guard import ScraperGuard

    guard = ScraperGuard(None)
    assert guard.acquire("any.domain") is True
    assert guard.is_banned("any.domain") is False


# ── Reconciliation ────────────────────────────────────────────────────────────


def test_reconciliation_creates_result_row():
    """reconcile_entry writes a ReconciliationResult row for a HIGH match."""
    db = _FakeDB()

    entry = {
        "id": 42,
        "court_id": "C1",
        "case_number": "CW/1234/2026",
        "hearing_date": "2026-05-17",
    }
    snapshot = {
        "id": str(uuid.uuid4()),
        "snapshot_json": json.dumps({
            "court_id": "C1",
            "case_number": "CW/1234/2026",
            "hearing_date": "2026-05-17",
        }),
    }

    from eventtrace.services.reconciliation import reconcile_entry
    result = reconcile_entry(db, entry, snapshot)

    assert result["confidence"] == "HIGH"
    assert "court_id" in result["matched_fields"]
    assert "case_number" in result["matched_fields"]
    assert "hearing_date" in result["matched_fields"]
    assert len(db._recon_results) == 1


def test_reconciliation_low_confidence_not_written():
    """run_reconciliation_batch skips LOW confidence pairs."""
    db = _FakeDB()

    entry = {"id": 1, "court_id": "C1", "case_number": "CW/9999/2026", "hearing_date": "2026-05-17"}
    snapshot = {
        "id": str(uuid.uuid4()),
        "snapshot_json": json.dumps({"court_id": "C99", "case_number": "DIFF/001/2000", "hearing_date": "2000-01-01"}),
    }

    from eventtrace.services.reconciliation import run_reconciliation_batch
    results = run_reconciliation_batch(db, [entry], [snapshot])

    # LOW confidence → no row written, results empty
    assert results == []
    assert len(db._recon_results) == 0

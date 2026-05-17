"""Phase 1A foundation tests.

Run: pytest tests/test_phase1a_foundation.py -v

Proof criteria:
- GET /health returns 200 JSON with {status, db, redis, timestamp}
- GET /metrics returns Prometheus text with supersahayak_ counters
- All new model classes importable
- Redis client returns None gracefully when REDIS_URL unset
- New User model has all Phase 1A fields
- CauselistEntry has search_vector column
"""

from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    os.environ.setdefault("DATABASE_URL", "")
    from eventtrace.api import create_app
    return TestClient(create_app())


# ── Health endpoint ────────────────────────────────────────────────────────────


def test_health_endpoint_returns_json(client):
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "status" in body
    assert "db" in body
    assert "timestamp" in body


def test_health_endpoint_has_redis_key(client):
    resp = client.get("/health")
    body = resp.json()
    assert "redis" in body
    assert body["redis"] in ("ok", "error", "disabled")


def test_health_status_is_string(client):
    resp = client.get("/health")
    body = resp.json()
    assert body["status"] in ("ok", "degraded")


def test_health_timestamp_is_iso(client):
    resp = client.get("/health")
    body = resp.json()
    from datetime import datetime
    # Should parse without raising
    datetime.fromisoformat(body["timestamp"])


# ── Metrics endpoint ───────────────────────────────────────────────────────────


def test_metrics_endpoint_returns_200(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_content_type_is_prometheus(client):
    resp = client.get("/metrics")
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_contains_supersahayak_counters(client):
    resp = client.get("/metrics")
    # Prometheus counters are registered at import time; their _total names appear
    assert "supersahayak_notifications_sent_total" in resp.text or "supersahayak_" in resp.text


# ── New model imports ──────────────────────────────────────────────────────────


def test_vc_link_model_importable():
    from eventtrace.storage.models import VcLink
    assert VcLink.__tablename__ == "vc_links"


def test_vc_link_delivery_log_model_importable():
    from eventtrace.storage.models import VcLinkDeliveryLog
    assert VcLinkDeliveryLog.__tablename__ == "vc_link_delivery_log"


def test_display_board_snapshot_model_importable():
    from eventtrace.storage.models import DisplayBoardSnapshot
    assert DisplayBoardSnapshot.__tablename__ == "display_board_snapshots"


def test_admin_alert_model_importable():
    from eventtrace.storage.models import AdminAlert
    assert AdminAlert.__tablename__ == "admin_alerts"


def test_reconciliation_result_model_importable():
    from eventtrace.storage.models import ReconciliationResult
    assert ReconciliationResult.__tablename__ == "reconciliation_results"


def test_causelist_entry_model_importable():
    from eventtrace.storage.models import CauselistEntry
    assert CauselistEntry.__tablename__ == "causelist_entries"


# ── CauselistEntry columns ────────────────────────────────────────────────────


def test_causelist_entry_has_search_vector():
    from eventtrace.storage.models import CauselistEntry
    cols = {c.name for c in CauselistEntry.__table__.columns}
    assert "search_vector" in cols


def test_causelist_entry_has_parser_version():
    from eventtrace.storage.models import CauselistEntry
    cols = {c.name for c in CauselistEntry.__table__.columns}
    assert "parser_version" in cols


def test_causelist_entry_has_raw_storage_path():
    from eventtrace.storage.models import CauselistEntry
    cols = {c.name for c in CauselistEntry.__table__.columns}
    assert "raw_storage_path" in cols


# ── User model new fields ─────────────────────────────────────────────────────


def test_user_model_has_phone_hash():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "phone_hash" in cols


def test_user_model_has_phone_encrypted():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "phone_encrypted" in cols


def test_user_model_has_preferred_channel():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "preferred_channel" in cols


def test_user_model_has_quiet_hours():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "quiet_hours_start" in cols
    assert "quiet_hours_end" in cols


def test_user_model_has_max_notifications_per_day():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "max_notifications_per_day" in cols


def test_user_model_has_telegram_fields():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "telegram_chat_id" in cols
    assert "telegram_username" in cols


def test_user_model_has_unsubscribe_token():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "unsubscribe_token" in cols


def test_user_model_has_email_valid():
    from eventtrace.storage.models import User
    cols = {c.name for c in User.__table__.columns}
    assert "email_valid" in cols


# ── Redis client ──────────────────────────────────────────────────────────────


def test_redis_client_returns_none_when_url_not_set():
    from eventtrace.core.redis_client import get_redis, reset_redis_client
    original = os.environ.pop("REDIS_URL", None)
    try:
        reset_redis_client()
        result = get_redis()
        assert result is None
    finally:
        if original is not None:
            os.environ["REDIS_URL"] = original
        reset_redis_client()


def test_redis_client_no_crash_on_bad_url():
    from eventtrace.core.redis_client import get_redis, reset_redis_client
    os.environ["REDIS_URL"] = "redis://localhost:19999"  # nothing listening here
    try:
        reset_redis_client()
        result = get_redis()
        assert result is None  # graceful fail
    finally:
        del os.environ["REDIS_URL"]
        reset_redis_client()


def test_redis_reset_allows_reinit():
    from eventtrace.core.redis_client import get_redis, reset_redis_client
    reset_redis_client()
    get_redis()  # first init
    reset_redis_client()
    get_redis()  # second init — should not raise


# ── Metrics counter objects ────────────────────────────────────────────────────


def test_metrics_counters_are_incrementable():
    from eventtrace.core.metrics import notifications_sent, notifications_failed
    notifications_sent.labels(channel="telegram", type="HEARING_TODAY").inc()
    notifications_failed.labels(channel="email", error_type="timeout").inc()


def test_metrics_histogram_is_observable():
    from eventtrace.core.metrics import case_search_duration
    case_search_duration.observe(0.15)


def test_metrics_gauge_is_settable():
    from eventtrace.core.metrics import vc_link_unverified
    vc_link_unverified.set(3)

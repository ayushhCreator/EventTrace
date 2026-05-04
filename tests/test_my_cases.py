"""Integration tests for /my-cases endpoints (SQLite backend)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_TEST_ENV = {
    "DATABASE_URL": "",
    "JWT_SECRET": "test-secret-eventtrace-abc123",
    "MSG91_AUTH_KEY": "",
    "MSG91_TEMPLATE_ID": "",
}

_SAMPLE_CASE = {
    "case_ref": "MAT/123/2024",
    "court_no": "1",
    "bench_label": "DB-I",
    "judges_json": json.dumps(["JUSTICE A", "JUSTICE B"]),
    "list_date": "2026-05-04",
    "serial_no": 5,
    "petitioner": "Ram v.",
    "respondent": "Shyam",
}


def _make_client():
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    env = {**_TEST_ENV, "CHD_DB_PATH": tmp.name}
    with patch.dict(os.environ, env, clear=False):
        import importlib
        import eventtrace.api as api_mod
        importlib.reload(api_mod)
        from fastapi.testclient import TestClient
        app = api_mod.create_app()
        return TestClient(app, raise_server_exceptions=True), tmp.name


def _register_and_login(client):
    """Return Bearer token for a fresh test user."""
    phone = "+919999900001"
    r = client.post("/auth/send-otp", json={"phone": phone})
    assert r.status_code == 200, r.text

    # Dev mode returns OTP in response body
    otp = r.json().get("dev_otp")
    assert otp, f"dev_otp missing: {r.json()}"

    r2 = client.post("/auth/verify-otp", json={"phone": phone, "otp": otp})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


class TestMyCasesEndpoints(unittest.TestCase):
    def setUp(self):
        self.client, self.db_path = _make_client()
        self.token = _register_and_login(self.client)
        self.auth = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        import os
        try:
            os.unlink(self.db_path)
        except Exception:
            pass

    # ── Auth guard ───────────────────────────────────────────────────────────

    def test_list_requires_auth(self):
        r = self.client.get("/my-cases")
        self.assertEqual(r.status_code, 401)

    def test_track_requires_auth(self):
        r = self.client.post("/my-cases", json=_SAMPLE_CASE)
        self.assertEqual(r.status_code, 401)

    # ── CRUD ────────────────────────────────────────────────────────────────

    def test_list_empty_initially(self):
        r = self.client.get("/my-cases", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_track_case(self):
        r = self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        self.assertIn(r.status_code, (200, 201), r.text)
        body = r.json()
        self.assertEqual(body["case_ref"], "MAT/123/2024")

    def test_track_idempotent(self):
        self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        r2 = self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        self.assertIn(r2.status_code, (200, 201))

        r3 = self.client.get("/my-cases", headers=self.auth)
        self.assertEqual(len(r3.json()), 1)

    def test_list_returns_tracked_case(self):
        self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        r = self.client.get("/my-cases", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        items = r.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["case_ref"], "MAT/123/2024")
        self.assertEqual(items[0]["bench_label"], "DB-I")

    def test_delete_case(self):
        self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        r = self.client.delete("/my-cases/MAT%2F123%2F2024", headers=self.auth)
        self.assertIn(r.status_code, (200, 204))
        r2 = self.client.get("/my-cases", headers=self.auth)
        self.assertEqual(r2.json(), [])

    # ── Alert ───────────────────────────────────────────────────────────────

    def test_set_alert(self):
        self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        r = self.client.post(
            "/my-cases/MAT%2F123%2F2024/alert",
            json={"alert_serial": 5, "look_ahead": 3},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 200)
        items = self.client.get("/my-cases", headers=self.auth).json()
        self.assertEqual(items[0]["alert_active"], 1)
        self.assertEqual(items[0]["alert_serial"], 5)
        self.assertEqual(items[0]["look_ahead"], 3)

    def test_clear_alert(self):
        self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        self.client.post(
            "/my-cases/MAT%2F123%2F2024/alert",
            json={"alert_serial": 5, "look_ahead": 3},
            headers=self.auth,
        )
        r = self.client.delete("/my-cases/MAT%2F123%2F2024/alert", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        items = self.client.get("/my-cases", headers=self.auth).json()
        self.assertEqual(items[0]["alert_active"], 0)

    def test_user_isolation(self):
        """Two users cannot see each other's cases."""
        # Register second user
        r = self.client.post("/auth/send-otp", json={"phone": "+919999900002"})
        otp2 = r.json()["dev_otp"]
        r2 = self.client.post("/auth/verify-otp", json={"phone": "+919999900002", "otp": otp2})
        token2 = r2.json()["token"]
        auth2 = {"Authorization": f"Bearer {token2}"}

        self.client.post("/my-cases", json=_SAMPLE_CASE, headers=self.auth)
        items = self.client.get("/my-cases", headers=auth2).json()
        self.assertEqual(items, [], "user2 must not see user1 cases")


if __name__ == "__main__":
    unittest.main()

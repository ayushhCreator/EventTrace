from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

# Build env patch used by all tests — forces SQLite, dev JWT, no MSG91
_TEST_ENV = {
    "DATABASE_URL": "",
    "JWT_SECRET": "test-secret-eventtrace-abc123",
    "MSG91_AUTH_KEY": "",
    "MSG91_TEMPLATE_ID": "",
}


def _make_client() -> TestClient:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    env = {**_TEST_ENV, "CHD_DB_PATH": tmp.name}
    with patch.dict(os.environ, env):
        from eventtrace.api import create_app
        app = create_app()
    return TestClient(app, raise_server_exceptions=True)


class TestHealth(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_ok(self):
        r = self.c.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")


class TestDisplayRoutes(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_current_state_empty(self):
        r = self.c.get("/current-state")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_event_traces_empty(self):
        r = self.c.get("/event-traces")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_changes_alias_works(self):
        r = self.c.get("/changes")
        self.assertEqual(r.status_code, 200)

    def test_absent_courts_empty(self):
        r = self.c.get("/absent-courts")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_field_durations_empty(self):
        r = self.c.get("/field-durations")
        self.assertEqual(r.status_code, 200)

    def test_vc_links_empty(self):
        r = self.c.get("/vc-links")
        self.assertEqual(r.status_code, 200)

    def test_vc_link_dates_empty(self):
        r = self.c.get("/vc-links/dates")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_event_traces_custom_limit(self):
        r = self.c.get("/event-traces?limit=10")
        self.assertEqual(r.status_code, 200)

    def test_event_traces_limit_over_max_422(self):
        r = self.c.get("/event-traces?limit=9999")
        self.assertEqual(r.status_code, 422)

    def test_event_traces_filter_by_court(self):
        r = self.c.get("/event-traces?court_id=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_field_state_unknown_court(self):
        r = self.c.get("/field-state/99")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])


class TestHistoryRoutes(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_dates_empty(self):
        r = self.c.get("/history/dates")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_day_empty(self):
        r = self.c.get("/history/day?date=2026-05-02")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_day_missing_date_param_422(self):
        r = self.c.get("/history/day")
        self.assertEqual(r.status_code, 422)


class TestCauselistRoutes(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_dates_empty(self):
        r = self.c.get("/causelist/dates")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_search_no_params_422(self):
        r = self.c.get("/causelist/search")
        self.assertEqual(r.status_code, 422)

    def test_search_by_advocate_empty(self):
        r = self.c.get("/causelist/search?advocate=Smith")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_search_by_party_empty(self):
        r = self.c.get("/causelist/search?party=Union+of+India")
        self.assertEqual(r.status_code, 200)

    def test_search_by_case_ref_empty(self):
        r = self.c.get("/causelist/search?case_ref=WP/123/2026")
        self.assertEqual(r.status_code, 200)

    def test_valid_date_empty(self):
        r = self.c.get("/causelist/2026-05-02")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_invalid_date_format_422(self):
        r = self.c.get("/causelist/01-05-2026")
        self.assertEqual(r.status_code, 422)

    def test_court_not_found_404(self):
        r = self.c.get("/causelist/2026-05-02/court/1")
        self.assertEqual(r.status_code, 404)

    def test_serial_not_found_404(self):
        r = self.c.get("/causelist/2026-05-02/court/1/serial/1")
        self.assertEqual(r.status_code, 404)


class TestAlertRoute(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_create_whatsapp_alert_201(self):
        r = self.c.post("/alert", json={
            "room_no": "5",
            "target_serial": 20,
            "contact_type": "whatsapp",
            "phone": "+919876543210",
        })
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertIn("id", data)
        self.assertEqual(data["room_no"], "5")
        self.assertEqual(data["target_serial"], 20)
        self.assertEqual(data["alert_at"], 15)  # 20 - 5 (default look_ahead)

    def test_custom_look_ahead(self):
        r = self.c.post("/alert", json={
            "room_no": "1",
            "target_serial": 10,
            "look_ahead": 3,
            "contact_type": "whatsapp",
            "phone": "+919876543210",
        })
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["alert_at"], 7)  # 10 - 3

    def test_telegram_command_in_response(self):
        r = self.c.post("/alert", json={
            "room_no": "2",
            "target_serial": 5,
            "contact_type": "telegram",
        })
        self.assertEqual(r.status_code, 201)
        self.assertIn("telegram_command", r.json())

    def test_whatsapp_without_phone_422(self):
        r = self.c.post("/alert", json={
            "room_no": "1",
            "target_serial": 10,
            "contact_type": "whatsapp",
        })
        self.assertEqual(r.status_code, 422)

    def test_invalid_contact_type_422(self):
        r = self.c.post("/alert", json={
            "room_no": "1",
            "target_serial": 10,
            "contact_type": "sms",
            "phone": "+919876543210",
        })
        self.assertEqual(r.status_code, 422)

    def test_target_serial_zero_422(self):
        r = self.c.post("/alert", json={
            "room_no": "1",
            "target_serial": 0,
            "contact_type": "whatsapp",
            "phone": "+919876543210",
        })
        self.assertEqual(r.status_code, 422)

    def test_hearing_date_invalid_format_422(self):
        r = self.c.post("/alert", json={
            "room_no": "1",
            "target_serial": 5,
            "contact_type": "whatsapp",
            "phone": "+919876543210",
            "hearing_date": "05/05/2026",
        })
        self.assertEqual(r.status_code, 422)


class TestAuthRoutes(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_me_no_token_401(self):
        r = self.c.get("/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_me_bad_token_401(self):
        r = self.c.get("/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
        self.assertEqual(r.status_code, 401)

    def test_send_otp_returns_dev_otp(self):
        r = self.c.post("/auth/send-otp", json={"phone": "+919876543210", "name": "Test User"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("dev_otp", data)
        self.assertEqual(len(data["dev_otp"]), 6)
        self.assertTrue(data["dev_otp"].isdigit())
        self.assertIn("expires_in", data)

    def test_send_otp_bare_number_normalized(self):
        r = self.c.post("/auth/send-otp", json={"phone": "9876500001"})
        self.assertEqual(r.status_code, 200)

    def test_send_otp_rate_limit_second_request(self):
        phone = "+919999000001"
        self.c.post("/auth/send-otp", json={"phone": phone})
        r = self.c.post("/auth/send-otp", json={"phone": phone})
        self.assertEqual(r.status_code, 429)

    def test_verify_otp_no_prior_otp_400(self):
        r = self.c.post("/auth/verify-otp", json={"phone": "+919900000099", "otp": "123456"})
        self.assertEqual(r.status_code, 400)

    def test_verify_otp_wrong_code_400(self):
        self.c.post("/auth/send-otp", json={"phone": "+919800000001"})
        r = self.c.post("/auth/verify-otp", json={"phone": "+919800000001", "otp": "000000"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Invalid OTP", r.json()["detail"])

    def test_full_otp_login_flow(self):
        phone = "+919988776655"

        # 1) Send OTP → dev_otp returned
        r1 = self.c.post("/auth/send-otp", json={"phone": phone, "name": "Advocate Roy"})
        self.assertEqual(r1.status_code, 200)
        dev_otp = r1.json()["dev_otp"]

        # 2) Verify OTP → token + user
        r2 = self.c.post("/auth/verify-otp", json={"phone": phone, "otp": dev_otp})
        self.assertEqual(r2.status_code, 200)
        data = r2.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["phone"], phone)
        self.assertEqual(data["user"]["name"], "Advocate Roy")
        self.assertEqual(data["user"]["verified"], 1)
        token = data["token"]

        # 3) GET /auth/me → authenticated user
        r3 = self.c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r3.status_code, 200)
        me = r3.json()
        self.assertEqual(me["phone"], phone)
        self.assertEqual(me["name"], "Advocate Roy")

    def test_update_profile_after_login(self):
        phone = "+919977665544"
        r1 = self.c.post("/auth/send-otp", json={"phone": phone})
        otp = r1.json()["dev_otp"]
        r2 = self.c.post("/auth/verify-otp", json={"phone": phone, "otp": otp})
        token = r2.json()["token"]

        r3 = self.c.patch(
            "/auth/me",
            json={"name": "New Name", "email": "new@example.com"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["name"], "New Name")
        self.assertEqual(r3.json()["email"], "new@example.com")

    def test_update_profile_no_token_401(self):
        r = self.c.patch("/auth/me", json={"name": "Hacker"})
        self.assertEqual(r.status_code, 401)

    def test_otp_attempt_cap(self):
        phone = "+919911223300"
        self.c.post("/auth/send-otp", json={"phone": phone})
        # Exhaust all 5 attempts
        for _ in range(5):
            self.c.post("/auth/verify-otp", json={"phone": phone, "otp": "000000"})
        # 6th attempt → 429
        r = self.c.post("/auth/verify-otp", json={"phone": phone, "otp": "000000"})
        self.assertEqual(r.status_code, 429)

    def test_two_users_independent(self):
        """Two phones each complete the OTP flow independently."""
        for i, phone in enumerate(["+919800000010", "+919800000011"]):
            r1 = self.c.post("/auth/send-otp", json={"phone": phone})
            otp = r1.json()["dev_otp"]
            r2 = self.c.post("/auth/verify-otp", json={"phone": phone, "otp": otp})
            self.assertEqual(r2.status_code, 200, f"phone {i} failed")
            token = r2.json()["token"]
            me = self.c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(me.json()["phone"], phone)


class TestExportRoutes(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_export_current_state_csv(self):
        r = self.c.get("/export/current-state.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("content-type", ""))

    def test_export_event_traces_csv(self):
        r = self.c.get("/export/event-traces.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()

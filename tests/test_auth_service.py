from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eventtrace.services import auth as auth_svc


class TestHashOtp(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(auth_svc.hash_otp("123456"), auth_svc.hash_otp("123456"))

    def test_different_inputs_differ(self):
        self.assertNotEqual(auth_svc.hash_otp("123456"), auth_svc.hash_otp("654321"))

    def test_returns_64_char_hex(self):
        h = auth_svc.hash_otp("000000")
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))


class TestIssueOtp(unittest.TestCase):
    def test_six_digit_numeric_string(self):
        for _ in range(100):
            otp = auth_svc.issue_otp()
            self.assertEqual(len(otp), 6)
            self.assertTrue(otp.isdigit())
            self.assertGreaterEqual(int(otp), 100000)
            self.assertLessEqual(int(otp), 999999)


class TestNormalizePhone(unittest.TestCase):
    def test_adds_91_to_bare_number(self):
        self.assertEqual(auth_svc.normalize_phone_value("9876543210"), "+919876543210")

    def test_keeps_plus_prefix(self):
        self.assertEqual(auth_svc.normalize_phone_value("+919876543210"), "+919876543210")

    def test_strips_spaces(self):
        self.assertEqual(auth_svc.normalize_phone_value("+91 98765 43210"), "+919876543210")

    def test_strips_dashes(self):
        self.assertEqual(auth_svc.normalize_phone_value("+91-98765-43210"), "+919876543210")

    def test_strips_parens(self):
        self.assertEqual(auth_svc.normalize_phone_value("+91(987)6543210"), "+919876543210")

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            auth_svc.normalize_phone_value("12345")

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            auth_svc.normalize_phone_value("abcdefghij")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            auth_svc.normalize_phone_value("")


class TestOtpRateLimited(unittest.TestCase):
    def _otp_row(self, seconds_remaining: float) -> dict:
        exp = datetime.now(timezone.utc) + timedelta(seconds=seconds_remaining)
        return {"expires_at": exp.isoformat()}

    def test_none_not_rate_limited(self):
        self.assertFalse(auth_svc.otp_rate_limited(None))

    def test_fresh_otp_is_rate_limited(self):
        # Full 10-min window remaining → within the 60s rate-limit window
        row = self._otp_row(auth_svc.OTP_EXPIRE_MINUTES * 60)
        self.assertTrue(auth_svc.otp_rate_limited(row))

    def test_otp_with_exactly_60s_remaining_not_rate_limited(self):
        # Exactly at boundary: 60s left → not rate limited
        row = self._otp_row(60)
        self.assertFalse(auth_svc.otp_rate_limited(row))

    def test_nearly_expired_otp_not_rate_limited(self):
        row = self._otp_row(30)
        self.assertFalse(auth_svc.otp_rate_limited(row))

    def test_already_expired_otp_not_rate_limited(self):
        row = self._otp_row(-60)
        self.assertFalse(auth_svc.otp_rate_limited(row))


class TestOtpExpired(unittest.TestCase):
    def test_past_datetime_str_expired(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.assertTrue(auth_svc.otp_expired(past))

    def test_future_datetime_str_not_expired(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.assertFalse(auth_svc.otp_expired(future))

    def test_past_datetime_object_expired(self):
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertTrue(auth_svc.otp_expired(past))

    def test_future_datetime_object_not_expired(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=30)
        self.assertFalse(auth_svc.otp_expired(future))

    def test_z_suffix_iso_string(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertTrue(auth_svc.otp_expired(past))


class TestJwt(unittest.TestCase):
    def _settings(self, secret: str = "test-jwt-secret-xyz") -> MagicMock:
        s = MagicMock()
        s.jwt_secret = secret
        return s

    def test_issue_and_decode_roundtrip(self):
        settings = self._settings()
        token = auth_svc.issue_jwt("user-abc-123", settings)
        payload = auth_svc.decode_jwt(token, settings)
        self.assertEqual(payload["sub"], "user-abc-123")

    def test_decoded_payload_has_exp_and_iat(self):
        settings = self._settings()
        token = auth_svc.issue_jwt("user-xyz", settings)
        payload = auth_svc.decode_jwt(token, settings)
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)

    def test_decode_invalid_token_raises_401(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            auth_svc.decode_jwt("not.a.valid.token", self._settings())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_decode_garbage_raises_401(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            auth_svc.decode_jwt("garbage", self._settings())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_decode_wrong_secret_raises_401(self):
        from fastapi import HTTPException
        token = auth_svc.issue_jwt("user-1", self._settings("secret-a"))
        with self.assertRaises(HTTPException) as ctx:
            auth_svc.decode_jwt(token, self._settings("secret-b"))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_different_users_get_different_tokens(self):
        settings = self._settings()
        t1 = auth_svc.issue_jwt("user-1", settings)
        t2 = auth_svc.issue_jwt("user-2", settings)
        self.assertNotEqual(t1, t2)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import ValidationError

from eventtrace.schemas.auth import SendOTPRequest, UpdateProfileRequest, VerifyOTPRequest
from eventtrace.schemas.alerts import AlertRequest


class TestSendOTPRequest(unittest.TestCase):
    def test_bare_number_gets_91_prefix(self):
        r = SendOTPRequest(phone="9876543210")
        self.assertEqual(r.phone, "+919876543210")

    def test_plus_prefix_preserved(self):
        r = SendOTPRequest(phone="+919876543210")
        self.assertEqual(r.phone, "+919876543210")

    def test_spaces_stripped(self):
        r = SendOTPRequest(phone="+91 98765 43210")
        self.assertEqual(r.phone, "+919876543210")

    def test_name_optional_defaults_none(self):
        r = SendOTPRequest(phone="+919876543210")
        self.assertIsNone(r.name)

    def test_name_stored(self):
        r = SendOTPRequest(phone="+919876543210", name="Advocate Singh")
        self.assertEqual(r.name, "Advocate Singh")

    def test_whatsapp_number_optional_defaults_none(self):
        r = SendOTPRequest(phone="+919876543210")
        self.assertIsNone(r.whatsapp_number)

    def test_whatsapp_number_normalizes(self):
        r = SendOTPRequest(phone="+919876543210", whatsapp_number="98765 43210")
        self.assertEqual(r.whatsapp_number, "+919876543210")

    def test_short_phone_rejected(self):
        with self.assertRaises(ValidationError):
            SendOTPRequest(phone="12345")

    def test_non_numeric_rejected(self):
        with self.assertRaises(ValidationError):
            SendOTPRequest(phone="notaphone")


class TestVerifyOTPRequest(unittest.TestCase):
    def test_normalizes_phone(self):
        r = VerifyOTPRequest(phone="9876543210", otp="123456")
        self.assertEqual(r.phone, "+919876543210")

    def test_otp_stored_as_is(self):
        r = VerifyOTPRequest(phone="+919876543210", otp="654321")
        self.assertEqual(r.otp, "654321")

    def test_invalid_phone_rejected(self):
        with self.assertRaises(ValidationError):
            VerifyOTPRequest(phone="abc", otp="123456")


class TestUpdateProfileRequest(unittest.TestCase):
    def test_all_optional(self):
        r = UpdateProfileRequest()
        self.assertIsNone(r.name)
        self.assertIsNone(r.email)
        self.assertIsNone(r.whatsapp_number)

    def test_name_and_email(self):
        r = UpdateProfileRequest(name="Alice", email="alice@example.com")
        self.assertEqual(r.name, "Alice")
        self.assertEqual(r.email, "alice@example.com")

    def test_whatsapp_number_normalizes(self):
        r = UpdateProfileRequest(whatsapp_number="9876543210")
        self.assertEqual(r.whatsapp_number, "+919876543210")


class TestAlertRequest(unittest.TestCase):
    def _valid(self, **kw) -> dict:
        base = {"room_no": "5", "target_serial": 20, "contact_type": "whatsapp", "phone": "+919876543210"}
        base.update(kw)
        return base

    def test_valid_whatsapp_alert(self):
        r = AlertRequest(**self._valid())
        self.assertEqual(r.room_no, "5")
        self.assertEqual(r.target_serial, 20)
        self.assertEqual(r.look_ahead, 5)  # default
        self.assertEqual(r.contact_type, "whatsapp")

    def test_look_ahead_default_five(self):
        r = AlertRequest(**self._valid())
        self.assertEqual(r.look_ahead, 5)

    def test_custom_look_ahead(self):
        r = AlertRequest(**self._valid(look_ahead=3))
        self.assertEqual(r.look_ahead, 3)

    def test_telegram_requires_no_phone(self):
        r = AlertRequest(room_no="1", target_serial=10, contact_type="telegram")
        self.assertIsNone(r.phone)

    def test_whatsapp_without_phone_rejected(self):
        with self.assertRaises(ValidationError):
            AlertRequest(room_no="1", target_serial=10, contact_type="whatsapp")

    def test_invalid_contact_type_rejected(self):
        with self.assertRaises(ValidationError):
            AlertRequest(**self._valid(contact_type="sms"))

    def test_valid_hearing_date(self):
        r = AlertRequest(**self._valid(hearing_date="2026-05-15"))
        self.assertEqual(r.hearing_date, "2026-05-15")

    def test_invalid_date_format_rejected(self):
        with self.assertRaises(ValidationError):
            AlertRequest(**self._valid(hearing_date="15-05-2026"))

    def test_invalid_date_slash_rejected(self):
        with self.assertRaises(ValidationError):
            AlertRequest(**self._valid(hearing_date="2026/05/15"))

    def test_target_serial_zero_rejected(self):
        with self.assertRaises(ValidationError):
            AlertRequest(**self._valid(target_serial=0))

    def test_target_serial_over_max_rejected(self):
        with self.assertRaises(ValidationError):
            AlertRequest(**self._valid(target_serial=10000))

    def test_target_serial_boundary_min(self):
        r = AlertRequest(**self._valid(target_serial=1))
        self.assertEqual(r.target_serial, 1)

    def test_target_serial_boundary_max(self):
        r = AlertRequest(**self._valid(target_serial=9999))
        self.assertEqual(r.target_serial, 9999)

    def test_contact_type_lowercased(self):
        r = AlertRequest(**self._valid(contact_type="WHATSAPP"))
        self.assertEqual(r.contact_type, "whatsapp")

    def test_display_name_optional(self):
        r = AlertRequest(**self._valid(display_name="My Land Case"))
        self.assertEqual(r.display_name, "My Land Case")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pydantic import BaseModel

from ..services.auth import normalize_phone_value

try:  # Pydantic v2
    from pydantic import field_validator
except ImportError:  # pragma: no cover (Pydantic v1 fallback)
    from pydantic import validator as field_validator


class SendOTPRequest(BaseModel):
    phone: str  # E.164 e.g. "+919876543210"
    name: str | None = None

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: str) -> str:
        return normalize_phone_value(v)


class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: str) -> str:
        return normalize_phone_value(v)


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    bar_enrollment_number: str | None = None
    firm_name: str | None = None
    secondary_email: str | None = None

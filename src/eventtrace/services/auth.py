from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from fastapi import HTTPException

from ..config import Settings
from .validators import ensure_utc_aware, parse_dt_maybe_iso

log = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30
OTP_EXPIRE_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def issue_jwt(user_id: str, settings: Settings) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def normalize_phone_value(phone: str) -> str:
    """Strip spaces/dashes, ensure +91 prefix for Indian numbers (pure; raises ValueError)."""
    phone = re.sub(r"[\s\-()]", "", (phone or ""))
    if not phone.startswith("+"):
        phone = "+91" + phone
    if not re.match(r"^\+\d{10,15}$", phone):
        raise ValueError("Invalid phone number")
    return phone


def normalize_phone_http(phone: str) -> str:
    try:
        return normalize_phone_value(phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def send_otp_msg91(phone: str, otp: str, settings: Settings) -> None:
    """Send OTP via MSG91. Raises on HTTP error."""
    if not settings.msg91_auth_key:
        log.warning("MSG91_AUTH_KEY not set — OTP not sent (dev mode, OTP logged)")
        log.warning("DEV OTP for %s: %s", phone, otp)
        return
    mobile = phone.lstrip("+")
    payload = {
        "template_id": settings.msg91_template_id,
        "mobile": mobile,
        "authkey": settings.msg91_auth_key,
        "otp": otp,
    }
    resp = httpx.post("https://api.msg91.com/api/v5/otp", json=payload, timeout=10)
    if resp.status_code >= 400:
        log.error("MSG91 error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="OTP delivery failed — try again")


def issue_otp() -> str:
    return str(secrets.randbelow(900000) + 100000)


def otp_rate_limited(existing_otp: dict | None) -> bool:
    if not existing_otp:
        return False
    exp = parse_dt_maybe_iso(existing_otp["expires_at"])
    remaining_window = (exp - datetime.now(timezone.utc)).total_seconds()
    return remaining_window > (OTP_EXPIRE_MINUTES * 60 - 60)


def otp_expired(expires_at: datetime | str) -> bool:
    exp = ensure_utc_aware(parse_dt_maybe_iso(expires_at))
    return datetime.now(timezone.utc) > exp

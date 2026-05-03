from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..schemas.auth import SendOTPRequest, UpdateProfileRequest, VerifyOTPRequest
from ..services import auth as auth_svc
from ..services.deps import get_db, get_settings

router = APIRouter(prefix="/auth")
_bearer = HTTPBearer(auto_error=False)


def _current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")
    payload = auth_svc.decode_jwt(credentials.credentials, settings)
    user = db.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/send-otp")
def send_otp(req: SendOTPRequest, db: Any = Depends(get_db), settings=Depends(get_settings)) -> dict:
    phone = req.phone
    existing = db.get_latest_otp(phone)
    if auth_svc.otp_rate_limited(existing):
        raise HTTPException(status_code=429, detail="OTP already sent — wait 60 seconds")

    otp = auth_svc.issue_otp()
    otp_hash = auth_svc.hash_otp(otp)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_svc.OTP_EXPIRE_MINUTES)

    db.upsert_user(phone, name=req.name)
    db.save_otp(phone, otp_hash, expires_at)
    auth_svc.send_otp_msg91(phone, otp, settings)

    dev = not settings.msg91_auth_key
    payload = {"detail": "OTP sent", "expires_in": auth_svc.OTP_EXPIRE_MINUTES * 60}
    if dev:
        payload["dev_otp"] = otp
    return payload


@router.post("/verify-otp")
def verify_otp(req: VerifyOTPRequest, db: Any = Depends(get_db), settings=Depends(get_settings)) -> dict:
    phone = req.phone
    record = db.get_latest_otp(phone)
    if not record:
        raise HTTPException(status_code=400, detail="No OTP found — request a new one")

    exp = auth_svc.parse_dt_maybe_iso(record["expires_at"])
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=400, detail="OTP expired")
    if record["attempts"] >= auth_svc.OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts — request a new OTP")

    db.increment_otp_attempts(record["id"])
    if auth_svc.hash_otp(req.otp) != record["otp_hash"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    db.mark_otp_used(record["id"])
    db.mark_user_verified(phone)
    user = db.get_user_by_phone(phone)
    token = auth_svc.issue_jwt(str(user["id"]), settings)
    return {"token": token, "user": user}


@router.get("/me")
def get_me(current_user: dict = Depends(_current_user)) -> dict:
    return current_user


@router.patch("/me")
def update_me(
    body: UpdateProfileRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    updated = db.update_user_profile(current_user["id"], body.name, body.email)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..schemas.auth import SendOTPRequest, UpdateProfileRequest, VerifyOTPRequest
from ..services import auth as auth_svc
from ..services.deps import get_db, get_settings

router = APIRouter(prefix="/auth")
_bearer = HTTPBearer(auto_error=False)
_limiter = Limiter(key_func=get_remote_address)

_COOKIE_NAME = "et_token"
_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days


def _set_auth_cookie(response: Response, token: str, settings) -> None:
    is_prod = bool(settings.database_url or settings.msg91_auth_key)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
        path="/",
    )


def _clear_auth_cookie(response: Response, settings) -> None:
    is_prod = bool(settings.database_url or settings.msg91_auth_key)
    response.delete_cookie(
        key=_COOKIE_NAME,
        httponly=True,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
        path="/",
    )


def _current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    # Cookie-first, Bearer fallback (transition period)
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        if credentials:
            token = credentials.credentials
        else:
            raise HTTPException(status_code=401, detail="Not authenticated")
    payload = auth_svc.decode_jwt(token, settings)
    user = db.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/send-otp")
@_limiter.limit("5/minute")
def send_otp(
    request: Request,
    req: SendOTPRequest,
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    phone = req.phone
    existing = db.get_latest_otp(phone)
    if auth_svc.otp_rate_limited(existing):
        raise HTTPException(status_code=429, detail="OTP already sent — wait 60 seconds")

    otp = auth_svc.issue_otp()
    otp_hash = auth_svc.hash_otp(otp, settings.otp_hmac_secret)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_svc.OTP_EXPIRE_MINUTES)

    db.upsert_user(phone, name=req.name)
    db.save_otp(phone, otp_hash, expires_at)
    auth_svc.send_otp_msg91(phone, otp, settings)

    dev = not settings.msg91_auth_key
    payload: dict = {"detail": "OTP sent", "expires_in": auth_svc.OTP_EXPIRE_MINUTES * 60}
    if dev:
        payload["dev_otp"] = otp
    return payload


@router.post("/verify-otp")
@_limiter.limit("10/minute")
def verify_otp(
    request: Request,
    response: Response,
    req: VerifyOTPRequest,
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
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
    if auth_svc.hash_otp(req.otp, settings.otp_hmac_secret) != record["otp_hash"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    db.mark_otp_used(record["id"])
    db.mark_user_verified(phone)
    user = db.get_user_by_phone(phone)
    token = auth_svc.issue_jwt(str(user["id"]), settings)

    _set_auth_cookie(response, token, settings)
    is_new = not user.get("name")
    return {"user": user, "is_new_user": is_new}


@router.post("/logout")
def logout(
    response: Response,
    settings=Depends(get_settings),
) -> dict:
    _clear_auth_cookie(response, settings)
    return {"detail": "Logged out"}


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


class NotificationPrefsUpdate(BaseModel):
    whatsapp: bool | None = None
    email: bool | None = None
    serial_alerts: bool | None = None
    causelist_alerts: bool | None = None
    change_alerts: bool | None = None


@router.get("/notification-settings")
def get_notification_settings(
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    return db.get_notification_prefs(current_user["id"])


@router.patch("/notification-settings")
def update_notification_settings(
    body: NotificationPrefsUpdate,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
) -> dict:
    current = db.get_notification_prefs(current_user["id"])
    updates = body.model_dump(exclude_none=True)
    merged = {**current, **updates}
    return db.update_notification_prefs(current_user["id"], merged)

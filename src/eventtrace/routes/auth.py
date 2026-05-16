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
_REFRESH_COOKIE_NAME = "et_refresh"
_ACCESS_MAX_AGE = auth_svc.ACCESS_TOKEN_EXPIRE_MINUTES * 60
_REFRESH_MAX_AGE = auth_svc.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600


def _cookie_flags(settings) -> dict:
    is_prod = bool(settings.database_url or settings.msg91_auth_key)
    return {
        "httponly": True,
        "secure": is_prod,
        "samesite": "none" if is_prod else "lax",
        "path": "/",
    }


def _set_auth_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        key=_COOKIE_NAME, value=token, max_age=_ACCESS_MAX_AGE, **_cookie_flags(settings)
    )


def _set_refresh_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME, value=token, max_age=_REFRESH_MAX_AGE, **_cookie_flags(settings)
    )


def _clear_auth_cookies(response: Response, settings) -> None:
    flags = _cookie_flags(settings)
    response.delete_cookie(key=_COOKIE_NAME, **flags)
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, **flags)


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

    db.upsert_user(phone, name=req.name, whatsapp_number=req.whatsapp_number)
    db.save_otp(phone, otp_hash, expires_at)
    auth_svc.send_otp_msg91(phone, otp, settings)

    dev = not settings.msg91_auth_key or not settings.msg91_template_id
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
    user_id = str(user["id"])

    # Phone IS the WhatsApp number — auto-verify on first login
    if not user.get("whatsapp_number"):
        db.set_whatsapp_verified(user_id, phone)
        user = db.get_user_by_phone(phone)

    access_token = auth_svc.issue_jwt(user_id, settings)
    refresh_token = auth_svc.issue_refresh_token()
    refresh_hash = auth_svc.hash_refresh_token(refresh_token)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=auth_svc.REFRESH_TOKEN_EXPIRE_DAYS)
    ).isoformat()
    db.save_refresh_token(user_id, refresh_hash, expires_at)

    _set_auth_cookie(response, access_token, settings)
    _set_refresh_cookie(response, refresh_token, settings)
    is_new = not user.get("name")

    if is_new:
        from ..services.notifications import send_welcome_whatsapp
        import threading
        threading.Thread(
            target=send_welcome_whatsapp,
            args=(phone, user.get("name") or ""),
            daemon=True,
        ).start()

    return {"user": user, "is_new_user": is_new}


@router.post("/refresh")
@_limiter.limit("10/minute")
def refresh(
    request: Request,
    response: Response,
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    token_hash = auth_svc.hash_refresh_token(token)
    record = db.get_refresh_token(token_hash)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")
    exp = auth_svc.parse_dt_maybe_iso(record["expires_at"])
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    # Rotate: revoke old, issue new
    db.revoke_refresh_token(token_hash)
    new_refresh = auth_svc.issue_refresh_token()
    new_refresh_hash = auth_svc.hash_refresh_token(new_refresh)
    new_expires = (
        datetime.now(timezone.utc) + timedelta(days=auth_svc.REFRESH_TOKEN_EXPIRE_DAYS)
    ).isoformat()
    db.save_refresh_token(record["user_id"], new_refresh_hash, new_expires)

    access_token = auth_svc.issue_jwt(record["user_id"], settings)
    _set_auth_cookie(response, access_token, settings)
    _set_refresh_cookie(response, new_refresh, settings)
    return {"detail": "ok"}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if token:
        db.revoke_refresh_token(auth_svc.hash_refresh_token(token))
    _clear_auth_cookies(response, settings)
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
    updated = db.update_user_profile(
        current_user["id"],
        name=body.name,
        email=body.email,
        whatsapp_number=body.whatsapp_number,
        role=body.role,
        bar_enrollment_number=body.bar_enrollment_number,
        firm_name=body.firm_name,
        secondary_email=body.secondary_email,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


class SendEmailOTPRequest(BaseModel):
    email: str


class VerifyEmailOTPRequest(BaseModel):
    email: str
    otp: str


@router.post("/email/send-otp")
@_limiter.limit("5/minute")
def send_email_otp(
    request: Request,
    body: SendEmailOTPRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    import re

    email = body.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    # Reject if this email is already verified by a different account
    existing_owner = db.get_user_by_email(email)
    if existing_owner and str(existing_owner["id"]) != str(current_user["id"]):
        raise HTTPException(status_code=409, detail="This email is already linked to another account")

    # Rate-limit: reuse phone OTP rate-limit logic (checks created_at < 60s ago)
    existing = db.get_latest_email_otp(email)
    if auth_svc.otp_rate_limited(existing):
        raise HTTPException(status_code=429, detail="OTP already sent — wait 60 seconds")

    otp = auth_svc.issue_otp()
    otp_hash = auth_svc.hash_otp(otp, settings.otp_hmac_secret)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_svc.OTP_EXPIRE_MINUTES)
    db.save_email_otp(email, current_user["id"], otp_hash, expires_at)

    from ..services.notifications import send_email_alert

    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px">
        <div style="width:36px;height:36px;background:#6750a4;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:14px;flex-shrink:0">SS</div>
        <span style="font-weight:700;color:#6750a4;font-size:16px">SuperSahayak Legal</span>
      </div>
      <h2 style="margin:0 0 8px;color:#1a1a2e;font-size:20px">Verify your email address</h2>
      <p style="color:#666;margin:0 0 24px;font-size:14px">Enter this code in the app to verify <strong>{email}</strong>.</p>
      <div style="background:#f4f0fb;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px">
        <span style="font-size:40px;font-weight:700;letter-spacing:10px;color:#6750a4;font-family:monospace">{otp}</span>
      </div>
      <p style="color:#999;font-size:12px;margin:0">Expires in {auth_svc.OTP_EXPIRE_MINUTES} minutes. Don't share this code with anyone.</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="color:#bbb;font-size:11px;margin:0">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """
    import os
    is_dev = not os.getenv("RESEND_API_KEY")

    ok = send_email_alert(email, "Your SuperSahayak Legal verification code", html)
    if not ok and not is_dev:
        raise HTTPException(
            status_code=503, detail="Failed to send email — check RESEND_API_KEY configuration"
        )

    payload: dict = {"detail": "OTP sent", "expires_in": auth_svc.OTP_EXPIRE_MINUTES * 60}
    if is_dev:
        payload["dev_otp"] = otp
    return payload


@router.post("/email/verify-otp")
@_limiter.limit("10/minute")
def verify_email_otp(
    request: Request,
    body: VerifyEmailOTPRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    email = body.email.strip().lower()
    record = db.get_latest_email_otp(email)
    if not record or record["user_id"] != str(current_user["id"]):
        raise HTTPException(
            status_code=400, detail="No OTP found for this email — request a new one"
        )

    exp = auth_svc.parse_dt_maybe_iso(record["expires_at"])
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=400, detail="OTP expired — request a new one")
    if record["attempts"] >= auth_svc.OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts — request a new OTP")

    db.increment_email_otp_attempts(record["id"])
    if auth_svc.hash_otp(body.otp, settings.otp_hmac_secret) != record["otp_hash"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    db.mark_email_otp_used(record["id"])
    user = db.set_email_verified(current_user["id"], email)
    return {"user": user, "detail": "Email verified"}


class SendWhatsappOTPRequest(BaseModel):
    whatsapp_number: str


class VerifyWhatsappOTPRequest(BaseModel):
    whatsapp_number: str
    otp: str


@router.post("/whatsapp/send-otp")
@_limiter.limit("3/minute")
def send_whatsapp_otp(
    request: Request,
    body: SendWhatsappOTPRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    import re

    number = body.whatsapp_number.strip()
    if not re.match(r"^\+?[0-9]{10,15}$", number):
        raise HTTPException(status_code=422, detail="Invalid WhatsApp number")

    existing = db.get_latest_whatsapp_otp_for_user(current_user["id"])
    if auth_svc.otp_rate_limited(existing):
        raise HTTPException(status_code=429, detail="OTP already sent — wait 60 seconds")

    otp = auth_svc.issue_otp()
    otp_hash = auth_svc.hash_otp(otp, settings.otp_hmac_secret)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_svc.OTP_EXPIRE_MINUTES)
    db.save_whatsapp_otp(number, current_user["id"], otp_hash, expires_at)

    auth_svc.send_otp_msg91(number, otp, settings, channel="whatsapp")

    return {"detail": "OTP sent", "expires_in": auth_svc.OTP_EXPIRE_MINUTES * 60}


@router.post("/whatsapp/verify-otp")
@_limiter.limit("10/minute")
def verify_whatsapp_otp(
    request: Request,
    body: VerifyWhatsappOTPRequest,
    current_user: dict = Depends(_current_user),
    db: Any = Depends(get_db),
    settings=Depends(get_settings),
) -> dict:
    number = body.whatsapp_number.strip()
    record = db.get_latest_whatsapp_otp(number)
    if not record or record["user_id"] != str(current_user["id"]):
        raise HTTPException(status_code=400, detail="No OTP found — request a new one")

    exp = auth_svc.parse_dt_maybe_iso(record["expires_at"])
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=400, detail="OTP expired — request a new one")
    if record["attempts"] >= auth_svc.OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts — request a new OTP")

    db.increment_whatsapp_otp_attempts(record["id"])
    if auth_svc.hash_otp(body.otp, settings.otp_hmac_secret) != record["otp_hash"]:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    db.mark_whatsapp_otp_used(record["id"])
    user = db.set_whatsapp_verified(current_user["id"], number)
    return {"user": user, "detail": "WhatsApp number verified"}


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

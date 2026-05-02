from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .config import Settings
from .db import get_db

_UI_DIR = Path(__file__).parent / "ui"
_log = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30
OTP_EXPIRE_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


# ── Auth models ───────────────────────────────────────────────────────────────

class SendOTPRequest(BaseModel):
    phone: str          # E.164 e.g. "+919876543210"
    name: str | None = None

class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str

class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: str | None = None


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _issue_jwt(user_id: str, settings: Settings) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── OTP helpers ───────────────────────────────────────────────────────────────

def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def _send_otp_msg91(phone: str, otp: str, settings: Settings) -> None:
    """Send OTP via MSG91. Raises on HTTP error."""
    if not settings.msg91_auth_key:
        _log.warning("MSG91_AUTH_KEY not set — OTP not sent (dev mode, OTP logged)")
        _log.info("DEV OTP for %s: %s", phone, otp)
        return
    # Remove leading + for MSG91
    mobile = phone.lstrip("+")
    payload = {
        "template_id": settings.msg91_template_id,
        "mobile": mobile,
        "authkey": settings.msg91_auth_key,
        "otp": otp,
    }
    resp = httpx.post(
        "https://api.msg91.com/api/v5/otp",
        json=payload,
        timeout=10,
    )
    if resp.status_code >= 400:
        _log.error("MSG91 error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="OTP delivery failed — try again")


def _normalize_phone(phone: str) -> str:
    """Strip spaces/dashes, ensure +91 prefix for Indian numbers."""
    phone = re.sub(r"[\s\-()]", "", phone)
    if not phone.startswith("+"):
        phone = "+91" + phone
    if not re.match(r"^\+\d{10,15}$", phone):
        raise HTTPException(status_code=422, detail="Invalid phone number")
    return phone


class AlertRequest(BaseModel):
    room_no: str
    target_serial: int = Field(..., ge=1, le=9999)
    look_ahead: int = Field(5, ge=0, le=50)
    hearing_date: str | None = None       # YYYY-MM-DD IST; defaults to today
    display_name: str | None = None
    contact_type: str = "whatsapp"        # 'whatsapp' | 'telegram' (telegram via deep link)
    phone: str | None = None              # E.164 e.g. "+919876543210" — required for whatsapp


def _today_ist() -> str:
    """Current date in IST as YYYY-MM-DD."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


log = logging.getLogger(__name__)


def _verify_twilio_signature(auth_token: str, signature: str, url: str, params: dict) -> bool:
    """Validate X-Twilio-Signature per Twilio's HMAC-SHA1 scheme."""
    # Build the string to sign: URL + sorted key=value pairs
    s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def create_app() -> FastAPI:
    settings = Settings()
    db = get_db(settings)
    db.ensure_schema()

    app = FastAPI(title="CHD EventTrace", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ───────────────────────────────────────────────────────────────

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ── Display board data ───────────────────────────────────────────────────

    @app.get("/current-state")
    def current_state() -> list[dict]:
        return db.list_current_state()

    @app.get("/vc-links")
    def vc_links(date: str | None = Query(None, description="YYYY-MM-DD IST, defaults to today")) -> dict[str, str]:
        return db.get_vc_zoom_links(date or _today_ist())

    @app.get("/vc-links/dates")
    def vc_link_dates() -> list[str]:
        return db.list_vc_dates()

    # ── Event traces ─────────────────────────────────────────────────────────

    @app.get("/changes")
    @app.get("/event-traces")
    def event_traces(
        limit: int = Query(200, ge=1, le=2000),
        court_id: str | None = None,
    ) -> list[dict]:
        return db.list_event_traces(limit=limit, court_id=court_id)

    @app.get("/field-state/{court_id}")
    def field_state(court_id: str) -> list[dict]:
        return db.list_field_state(court_id)

    @app.get("/absent-courts")
    def absent_courts() -> list[str]:
        """Court IDs that have left the live board (__present__ = '0')."""
        return db.list_absent_court_ids()

    @app.get("/field-durations")
    def field_durations() -> dict[str, str]:
        """Returns {court_id: serial_start_time ISO} for all courts."""
        return db.list_serial_start_times()

    # ── History ──────────────────────────────────────────────────────────────

    @app.get("/history/dates")
    def history_dates() -> list[str]:
        return db.list_active_dates()

    @app.get("/history/day")
    def history_day(date: str = Query(..., description="YYYY-MM-DD in IST")) -> list[dict]:
        return db.list_day_activity(date)

    # ── Exports ──────────────────────────────────────────────────────────────

    @app.get("/export/current-state.csv")
    def export_current_state_csv():
        rows = db.list_current_state()
        if not rows:
            return StreamingResponse(
                io.StringIO("court_id,last_seen_time\n"),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=current_state.csv"},
            )
        all_keys: list[str] = []
        for r in rows:
            for k in r["data"].keys():
                if k not in all_keys:
                    all_keys.append(k)
        fieldnames = ["court_id", "last_seen_time"] + all_keys
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            flat = {"court_id": r["court_id"], "last_seen_time": r["last_seen_time"]}
            flat.update(r["data"])
            writer.writerow(flat)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=current_state.csv"},
        )

    @app.get("/export/event-traces.csv")
    def export_event_traces_csv(
        limit: int = Query(2000, ge=1, le=100000),
        court_id: str | None = None,
    ):
        rows = db.list_event_traces(limit=limit, court_id=court_id)
        fieldnames = ["id", "court_id", "field_name", "old_value", "new_value",
                      "start_time", "end_time", "duration_seconds", "observed_time"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=event_traces.csv"},
        )

    # ── Alert signup ─────────────────────────────────────────────────────────

    _alert_api_key = os.getenv("CHD_ALERT_API_KEY", "")

    @app.post("/alert", status_code=201)
    def create_alert(req: AlertRequest, x_api_key: str | None = Header(default=None)) -> dict:
        if _alert_api_key and x_api_key != _alert_api_key:
            raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key")
        date = req.hearing_date or _today_ist()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise HTTPException(status_code=422, detail="hearing_date must be YYYY-MM-DD")

        phone = (req.phone or "").strip()
        if req.contact_type == "whatsapp":
            if not phone:
                raise HTTPException(status_code=422, detail="phone is required for WhatsApp alerts")
            # Normalise: ensure E.164 with leading +
            if not phone.startswith("+"):
                phone = "+" + phone

        sub_id = db.add_subscription(
            telegram_id="",
            room_no=req.room_no,
            target_serial=req.target_serial,
            look_ahead=req.look_ahead,
            hearing_date=date,
            contact_type=req.contact_type,
            display_name=req.display_name,
            phone=phone or None,
        )
        alert_at = req.target_serial - req.look_ahead
        bot_cmd = f"/watch {req.room_no} {req.target_serial} {req.look_ahead} {date}"
        return {
            "id": sub_id,
            "room_no": req.room_no,
            "target_serial": req.target_serial,
            "alert_at": alert_at,
            "hearing_date": date,
            "contact_type": req.contact_type,
            "telegram_command": bot_cmd,
        }

    # ── WhatsApp webhook (Twilio inbound) ────────────────────────────────────

    @app.post("/webhook/whatsapp", response_class=HTMLResponse)
    async def whatsapp_webhook(request: Request) -> HTMLResponse:
        """Twilio calls this with form-encoded data for every inbound WhatsApp message."""
        from .whatsapp_bot import handle_inbound
        form = await request.form()
        form_dict = dict(form)

        # Verify Twilio signature when auth token is configured
        if settings.twilio_auth_token:
            sig = request.headers.get("X-Twilio-Signature", "")
            # Behind ngrok/reverse proxy, reconstruct the public URL Twilio signed against.
            # CHD_PUBLIC_URL overrides (e.g. "https://abc.ngrok-free.app"); fallback to request.url.
            public_base = os.getenv("CHD_PUBLIC_URL", "").rstrip("/")
            url = (public_base + str(request.url.path)) if public_base else str(request.url)
            if not _verify_twilio_signature(settings.twilio_auth_token, sig, url, form_dict):
                log.warning("WhatsApp webhook: invalid Twilio signature from %s", request.client)
                raise HTTPException(status_code=403, detail="Invalid signature")

        try:
            reply = handle_inbound(form_dict, db)
        except Exception as exc:
            log.error("WhatsApp webhook error: %s", exc)
            reply = "Sorry, something went wrong. Try again."
        # Twilio expects TwiML XML response
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Message>{reply}</Message></Response>"
        )
        return HTMLResponse(content=twiml, media_type="application/xml")

    # ── Causelist ────────────────────────────────────────────────────────────
    # NOTE: static paths (/dates, /search) MUST come before /{list_date} or
    # FastAPI matches "dates"/"search" as a list_date value.

    @app.get("/causelist/dates")
    def causelist_dates() -> list[str]:
        return db.list_causelist_dates()

    @app.get("/causelist/search")
    def causelist_search(
        case_ref: str | None = Query(None),
        advocate: str | None = Query(None),
        party: str | None = Query(None),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
    ) -> list[dict]:
        if not any([case_ref, advocate, party]):
            raise HTTPException(status_code=422, detail="Provide at least one of: case_ref, advocate, party")
        return db.search_causelist_cases(
            case_ref=case_ref, advocate=advocate, party=party,
            date_from=date_from, date_to=date_to, limit=limit,
        )

    @app.get("/causelist/{list_date}")
    def causelist_summary(list_date: str) -> list[dict]:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", list_date):
            raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
        return db.list_causelist_benches(list_date)

    @app.get("/causelist/{list_date}/court/{court_no}")
    def causelist_court(list_date: str, court_no: str) -> dict:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", list_date):
            raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
        bench = db.get_causelist_bench(list_date, court_no)
        if not bench:
            raise HTTPException(status_code=404, detail="Court not found for that date")
        cases = db.list_causelist_cases(list_date, court_no)
        return {"bench": bench, "cases": cases}

    @app.get("/causelist/{list_date}/court/{court_no}/serial/{serial_no}")
    def causelist_serial(list_date: str, court_no: str, serial_no: int) -> dict:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", list_date):
            raise HTTPException(status_code=422, detail="list_date must be YYYY-MM-DD")
        row = db.get_causelist_case_by_serial(list_date, court_no, serial_no)
        if not row:
            raise HTTPException(status_code=404, detail="Case not found")
        return row

    # ── Auth endpoints ────────────────────────────────────────────────────────

    def _current_user(credentials: HTTPAuthorizationCredentials | None = Security(_bearer)) -> dict:
        if not credentials:
            raise HTTPException(status_code=401, detail="Authorization header required")
        payload = _decode_jwt(credentials.credentials, settings)
        user = db.get_user_by_id(payload["sub"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    @app.post("/auth/send-otp")
    def send_otp(req: SendOTPRequest) -> dict:
        phone = _normalize_phone(req.phone)
        # Rate limit: check if a valid unused OTP was issued in the last 60s
        existing = db.get_latest_otp(phone)
        if existing:
            exp = existing["expires_at"]
            if hasattr(exp, "tzinfo") and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            remaining_window = (exp - datetime.now(timezone.utc)).total_seconds()
            if remaining_window > (OTP_EXPIRE_MINUTES * 60 - 60):
                raise HTTPException(status_code=429, detail="OTP already sent — wait 60 seconds")
        otp = str(secrets.randbelow(900000) + 100000)   # 6-digit
        otp_hash = _hash_otp(otp)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
        db.upsert_user(phone, name=req.name)
        db.save_otp(phone, otp_hash, expires_at)
        _send_otp_msg91(phone, otp, settings)
        return {"detail": "OTP sent", "expires_in": OTP_EXPIRE_MINUTES * 60}

    @app.post("/auth/verify-otp")
    def verify_otp(req: VerifyOTPRequest) -> dict:
        phone = _normalize_phone(req.phone)
        record = db.get_latest_otp(phone)
        if not record:
            raise HTTPException(status_code=400, detail="No OTP found — request a new one")
        exp = record["expires_at"]
        if hasattr(exp, "tzinfo") and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            raise HTTPException(status_code=400, detail="OTP expired")
        if record["attempts"] >= OTP_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many attempts — request a new OTP")
        db.increment_otp_attempts(record["id"])
        if _hash_otp(req.otp) != record["otp_hash"]:
            raise HTTPException(status_code=400, detail="Invalid OTP")
        db.mark_otp_used(record["id"])
        db.mark_user_verified(phone)
        user = db.get_user_by_phone(phone)
        token = _issue_jwt(str(user["id"]), settings)
        return {"token": token, "user": user}

    @app.get("/auth/me")
    def get_me(current_user: dict = Depends(_current_user)) -> dict:
        return current_user

    @app.patch("/auth/me")
    def update_me(body: UpdateProfileRequest, current_user: dict = Depends(_current_user)) -> dict:
        updated = db.update_user_profile(current_user["id"], body.name, body.email)
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return updated

    # ── UI pages ─────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    @app.get("/ui", response_class=HTMLResponse)
    def ui_display():
        return HTMLResponse((_UI_DIR / "index.html").read_text())

    @app.get("/admin", response_class=HTMLResponse)
    def ui_admin():
        return HTMLResponse((_UI_DIR / "admin.html").read_text())

    return app


def main() -> None:
    import uvicorn

    host = os.getenv("CHD_API_HOST", "127.0.0.1")
    port = int(os.getenv("PORT") or os.getenv("CHD_API_PORT", "8009"))
    reload_env = os.getenv("CHD_API_RELOAD", "0").strip().lower()
    reload_enabled = reload_env in {"1", "true", "yes", "on"}
    uvicorn.run("eventtrace.api:create_app", host=host, port=port, factory=True, reload=reload_enabled)

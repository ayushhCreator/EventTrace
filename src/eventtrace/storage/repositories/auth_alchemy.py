"""SQLAlchemy-based auth repository.

Single implementation for both SQLite and PostgreSQL.
Replaces SQLiteAuthRepository + PostgresAuthRepository.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ...common.time import iso, utc_now
from ..models import EmailOtp, PhoneOtp, RefreshToken, User, WhatsappOtp


def _user_to_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "phone": user.phone,
        "whatsapp_number": getattr(user, "whatsapp_number", None),
        "whatsapp_verified": bool(getattr(user, "whatsapp_verified", 0)),
        "daily_wa_cap": getattr(user, "daily_wa_cap", 20),
        "email": user.email,
        "email_verified": bool(user.email_verified),
        "name": user.name,
        "role": user.role,
        "tier": user.tier,
        "verified": user.verified,
        "notification_prefs": user.notification_prefs,
        "bar_enrollment_number": user.bar_enrollment_number,
        "firm_name": user.firm_name,
        "secondary_email": user.secondary_email,
        "is_admin": bool(user.is_admin),
    }


def _whatsapp_otp_to_dict(otp: WhatsappOtp) -> dict:
    return {
        "id": otp.id,
        "whatsapp_number": otp.whatsapp_number,
        "user_id": otp.user_id,
        "otp_hash": otp.otp_hash,
        "expires_at": otp.expires_at,
        "attempts": otp.attempts,
        "used": otp.used,
    }


def _email_otp_to_dict(otp: EmailOtp) -> dict:
    return {
        "id": otp.id,
        "email": otp.email,
        "user_id": otp.user_id,
        "otp_hash": otp.otp_hash,
        "expires_at": otp.expires_at,
        "attempts": otp.attempts,
        "used": otp.used,
    }


def _otp_to_dict(otp: PhoneOtp) -> dict:
    return {
        "id": otp.id,
        "phone": otp.phone,
        "otp_hash": otp.otp_hash,
        "expires_at": otp.expires_at,
        "attempts": otp.attempts,
        "used": otp.used,
    }


_DEFAULT_PREFS = {
    "whatsapp": True,
    "email": True,
    "serial_alerts": True,
    "causelist_alerts": True,
    "change_alerts": True,
}


class SQLAlchemyAuthRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_user_by_phone(self, phone: str) -> dict | None:
        with Session(self._engine) as session:
            user = session.scalar(select(User).where(User.phone == phone))
            return _user_to_dict(user) if user else None

    def get_user_by_id(self, user_id: str) -> dict | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            return _user_to_dict(user) if user else None

    def get_user_by_email(self, email: str) -> dict | None:
        with Session(self._engine) as session:
            user = session.scalar(
                select(User).where(User.email == email.strip().lower(), User.email_verified == 1)
            )
            return _user_to_dict(user) if user else None

    def upsert_user(
        self,
        phone: str,
        name: str | None = None,
        email: str | None = None,
        whatsapp_number: str | None = None,
    ) -> dict:
        with Session(self._engine) as session:
            user = session.scalar(select(User).where(User.phone == phone))
            if user:
                if name and not user.name:
                    user.name = name
                if email and not user.email:
                    user.email = email
                if whatsapp_number and not getattr(user, "whatsapp_number", None):
                    user.whatsapp_number = whatsapp_number
            else:
                user = User(
                    id=str(uuid.uuid4()),
                    phone=phone,
                    whatsapp_number=whatsapp_number or phone,
                    name=name,
                    email=email,
                    verified=0,
                    created_at=iso(utc_now()),
                )
                session.add(user)
            session.commit()
            session.refresh(user)
            return _user_to_dict(user)

    def mark_user_verified(self, phone: str) -> None:
        with Session(self._engine) as session:
            session.execute(update(User).where(User.phone == phone).values(verified=1))
            session.commit()

    def save_otp(self, phone: str, otp_hash: str, expires_at: Any) -> None:
        now = iso(utc_now())
        if not isinstance(expires_at, str):
            expires_at = iso(expires_at)
        with Session(self._engine) as session:
            otp = PhoneOtp(
                phone=phone,
                otp_hash=otp_hash,
                expires_at=expires_at,
                attempts=0,
                used=0,
                created_at=now,
            )
            session.add(otp)
            session.commit()

    def get_latest_otp(self, phone: str) -> dict | None:
        with Session(self._engine) as session:
            otp = session.scalar(
                select(PhoneOtp)
                .where(PhoneOtp.phone == phone, PhoneOtp.used == 0)
                .order_by(PhoneOtp.id.desc())
                .limit(1)
            )
            return _otp_to_dict(otp) if otp else None

    def increment_otp_attempts(self, otp_id: int) -> None:
        with Session(self._engine) as session:
            otp = session.get(PhoneOtp, otp_id)
            if otp:
                otp.attempts += 1
                session.commit()

    def mark_otp_used(self, otp_id: int) -> None:
        with Session(self._engine) as session:
            otp = session.get(PhoneOtp, otp_id)
            if otp:
                otp.used = 1
                session.commit()

    def update_user_profile(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
        whatsapp_number: str | None = None,
        role: str | None = None,
        bar_enrollment_number: str | None = None,
        firm_name: str | None = None,
        secondary_email: str | None = None,
    ) -> dict | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if not user:
                return None
            if name is not None:
                user.name = name
            if email is not None:
                user.email = email
            if whatsapp_number is not None:
                user.whatsapp_number = whatsapp_number
            if role is not None:
                user.role = role
            if bar_enrollment_number is not None:
                user.bar_enrollment_number = bar_enrollment_number
            if firm_name is not None:
                user.firm_name = firm_name
            if secondary_email is not None:
                user.secondary_email = secondary_email
            session.commit()
            session.refresh(user)
            return _user_to_dict(user)

    def get_notification_prefs(self, user_id: str) -> dict:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if not user or not user.notification_prefs:
                return dict(_DEFAULT_PREFS)
            try:
                return {**_DEFAULT_PREFS, **json.loads(user.notification_prefs)}
            except Exception:
                return dict(_DEFAULT_PREFS)

    def update_notification_prefs(self, user_id: str, prefs: dict) -> dict:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if user:
                user.notification_prefs = json.dumps(prefs)
                session.commit()
        return prefs

    def save_refresh_token(self, user_id: str, token_hash: str, expires_at: str) -> None:
        with Session(self._engine) as session:
            rt = RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                revoked=0,
                created_at=iso(utc_now()),
            )
            session.add(rt)
            session.commit()

    def get_refresh_token(self, token_hash: str) -> dict | None:
        with Session(self._engine) as session:
            rt = session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.revoked == 0,
                )
            )
            if not rt:
                return None
            return {
                "id": rt.id,
                "user_id": rt.user_id,
                "expires_at": rt.expires_at,
                "revoked": rt.revoked,
            }

    def revoke_refresh_token(self, token_hash: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(RefreshToken).where(RefreshToken.token_hash == token_hash).values(revoked=1)
            )
            session.commit()

    def revoke_all_user_refresh_tokens(self, user_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=1)
            )
            session.commit()

    # ── Email OTP ─────────────────────────────────────────────────────────────

    def save_email_otp(self, email: str, user_id: str, otp_hash: str, expires_at: Any) -> None:
        now = iso(utc_now())
        if not isinstance(expires_at, str):
            expires_at = iso(expires_at)
        with Session(self._engine) as session:
            otp = EmailOtp(
                email=email,
                user_id=user_id,
                otp_hash=otp_hash,
                expires_at=expires_at,
                attempts=0,
                used=0,
                created_at=now,
            )
            session.add(otp)
            session.commit()

    def get_latest_email_otp(self, email: str) -> dict | None:
        with Session(self._engine) as session:
            otp = session.scalar(
                select(EmailOtp)
                .where(EmailOtp.email == email, EmailOtp.used == 0)
                .order_by(EmailOtp.id.desc())
                .limit(1)
            )
            return _email_otp_to_dict(otp) if otp else None

    def get_latest_email_otp_for_user(self, user_id: str) -> dict | None:
        with Session(self._engine) as session:
            otp = session.scalar(
                select(EmailOtp)
                .where(EmailOtp.user_id == user_id, EmailOtp.used == 0)
                .order_by(EmailOtp.id.desc())
                .limit(1)
            )
            return _email_otp_to_dict(otp) if otp else None

    def increment_email_otp_attempts(self, otp_id: int) -> None:
        with Session(self._engine) as session:
            otp = session.get(EmailOtp, otp_id)
            if otp:
                otp.attempts += 1
                session.commit()

    def mark_email_otp_used(self, otp_id: int) -> None:
        with Session(self._engine) as session:
            otp = session.get(EmailOtp, otp_id)
            if otp:
                otp.used = 1
                session.commit()

    def set_email_verified(self, user_id: str, email: str) -> dict | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if not user:
                return None
            user.email = email
            user.email_verified = 1
            session.commit()
            session.refresh(user)
            return _user_to_dict(user)

    # ── WhatsApp OTP ──────────────────────────────────────────────────────────

    def save_whatsapp_otp(self, whatsapp_number: str, user_id: str, otp_hash: str, expires_at: Any) -> None:
        now = iso(utc_now())
        if not isinstance(expires_at, str):
            expires_at = iso(expires_at)
        with Session(self._engine) as session:
            otp = WhatsappOtp(
                whatsapp_number=whatsapp_number,
                user_id=user_id,
                otp_hash=otp_hash,
                expires_at=expires_at,
                attempts=0,
                used=0,
                created_at=now,
            )
            session.add(otp)
            session.commit()

    def get_latest_whatsapp_otp(self, whatsapp_number: str) -> dict | None:
        with Session(self._engine) as session:
            otp = session.scalar(
                select(WhatsappOtp)
                .where(WhatsappOtp.whatsapp_number == whatsapp_number, WhatsappOtp.used == 0)
                .order_by(WhatsappOtp.id.desc())
                .limit(1)
            )
            return _whatsapp_otp_to_dict(otp) if otp else None

    def get_latest_whatsapp_otp_for_user(self, user_id: str) -> dict | None:
        with Session(self._engine) as session:
            otp = session.scalar(
                select(WhatsappOtp)
                .where(WhatsappOtp.user_id == user_id, WhatsappOtp.used == 0)
                .order_by(WhatsappOtp.id.desc())
                .limit(1)
            )
            return _whatsapp_otp_to_dict(otp) if otp else None

    def increment_whatsapp_otp_attempts(self, otp_id: int) -> None:
        with Session(self._engine) as session:
            otp = session.get(WhatsappOtp, otp_id)
            if otp:
                otp.attempts += 1
                session.commit()

    def mark_whatsapp_otp_used(self, otp_id: int) -> None:
        with Session(self._engine) as session:
            otp = session.get(WhatsappOtp, otp_id)
            if otp:
                otp.used = 1
                session.commit()

    def set_whatsapp_verified(self, user_id: str, whatsapp_number: str) -> dict | None:
        with Session(self._engine) as session:
            user = session.get(User, user_id)
            if not user:
                return None
            user.whatsapp_number = whatsapp_number
            user.whatsapp_verified = 1
            session.commit()
            session.refresh(user)
            return _user_to_dict(user)

    def get_user_stats(self) -> dict:
        with Session(self._engine) as session:
            total = session.scalar(select(func.count()).select_from(User)) or 0
            wa_verified = session.scalar(
                select(func.count()).select_from(User).where(User.whatsapp_verified == 1)
            ) or 0
            with_phone = session.scalar(
                select(func.count()).select_from(User).where(User.phone.isnot(None))
            ) or 0
            admins = session.scalar(
                select(func.count()).select_from(User).where(User.is_admin == 1)
            ) or 0
        return {
            "total_users": total,
            "whatsapp_verified": wa_verified,
            "with_phone": with_phone,
            "admins": admins,
        }

    def list_all_users_with_stats(self) -> list[dict]:
        from sqlalchemy import text

        sql = text("""
            SELECT
                u.id,
                u.phone,
                u.name,
                u.email,
                u.role,
                u.tier,
                u.verified,
                u.whatsapp_verified,
                u.whatsapp_number,
                u.is_admin,
                u.created_at,
                u.bar_enrollment_number,
                u.firm_name,
                COALESCE(tc.case_count, 0) AS tracked_cases,
                COALESCE(al.alert_count, 0) AS active_alerts
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS case_count
                FROM tracked_cases
                GROUP BY user_id
            ) tc ON tc.user_id = u.id
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS alert_count
                FROM tracked_cases
                WHERE alert_serial IS NOT NULL
                GROUP BY user_id
            ) al ON al.user_id = u.id
            ORDER BY u.created_at DESC
        """)
        with Session(self._engine) as session:
            rows = session.execute(sql).fetchall()
        return [dict(r._mapping) for r in rows]

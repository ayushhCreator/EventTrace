"""Repositories for auth tables: users, phone_otps."""

from __future__ import annotations

import uuid
from typing import Any

from ...common.time import iso, utc_now


class SQLiteAuthRepository:
    """SQLite-backed repository for users and phone_otps."""

    def __init__(self, connect_fn) -> None:
        self._connect = connect_fn

    def get_user_by_phone(self, phone: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT id, phone, email, name, role, tier, verified FROM users WHERE phone = ?",
                (phone,),
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT id, phone, email, name, role, tier, verified FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_user(self, phone: str, name: str | None = None, email: str | None = None) -> dict:
        now = iso(utc_now())
        user_id = str(uuid.uuid4())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO users (id, phone, name, email, verified, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT (phone) DO UPDATE SET
                  name  = COALESCE(excluded.name, users.name),
                  email = COALESCE(excluded.email, users.email)
                """,
                (user_id, phone, name, email, now),
            )
            row = con.execute(
                "SELECT id, phone, email, name, role, tier, verified FROM users WHERE phone = ?",
                (phone,),
            ).fetchone()
            return dict(row)

    def mark_user_verified(self, phone: str) -> None:
        with self._connect() as con:
            con.execute("UPDATE users SET verified = 1 WHERE phone = ?", (phone,))

    def save_otp(self, phone: str, otp_hash: str, expires_at: Any) -> None:
        now = iso(utc_now())
        if not isinstance(expires_at, str):
            expires_at = iso(expires_at)
        with self._connect() as con:
            con.execute(
                "INSERT INTO phone_otps (phone, otp_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (phone, otp_hash, expires_at, now),
            )

    def get_latest_otp(self, phone: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id, phone, otp_hash, expires_at, attempts, used
                FROM phone_otps
                WHERE phone = ? AND used = 0
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (phone,),
            ).fetchone()
            return dict(row) if row else None

    def increment_otp_attempts(self, otp_id: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE phone_otps SET attempts = attempts + 1 WHERE id = ?", (otp_id,))

    def mark_otp_used(self, otp_id: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE phone_otps SET used = 1 WHERE id = ?", (otp_id,))

    def update_user_profile(self, user_id: str, name: str | None, email: str | None) -> dict | None:
        with self._connect() as con:
            con.execute(
                """
                UPDATE users SET
                  name  = COALESCE(?, name),
                  email = COALESCE(?, email)
                WHERE id = ?
                """,
                (name, email, user_id),
            )
            row = con.execute(
                "SELECT id, phone, email, name, role, tier, verified FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None


class PostgresAuthRepository:
    """PostgreSQL-backed repository for users and phone_otps."""

    def __init__(self, cursor_ctx) -> None:
        self._cursor = cursor_ctx

    def get_user_by_phone(self, phone: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, phone, email, name, role, tier, verified FROM users WHERE phone = %s",
                (phone,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def get_user_by_id(self, user_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, phone, email, name, role, tier, verified FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def upsert_user(self, phone: str, name: str | None = None, email: str | None = None) -> dict:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (phone, name, email, verified)
                VALUES (%s, %s, %s, 0)
                ON CONFLICT (phone) DO UPDATE SET
                  name  = COALESCE(EXCLUDED.name, users.name),
                  email = COALESCE(EXCLUDED.email, users.email)
                RETURNING id, phone, email, name, role, tier, verified
                """,
                (phone, name, email),
            )
            return dict(cur.fetchone())

    def mark_user_verified(self, phone: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE users SET verified = 1 WHERE phone = %s", (phone,))

    def save_otp(self, phone: str, otp_hash: str, expires_at: Any) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO phone_otps (phone, otp_hash, expires_at) VALUES (%s, %s, %s)",
                (phone, otp_hash, expires_at),
            )

    def get_latest_otp(self, phone: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id, phone, otp_hash, expires_at, attempts, used
                FROM phone_otps
                WHERE phone = %s AND used = 0
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (phone,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def increment_otp_attempts(self, otp_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE phone_otps SET attempts = attempts + 1 WHERE id = %s", (otp_id,))

    def mark_otp_used(self, otp_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE phone_otps SET used = 1 WHERE id = %s", (otp_id,))

    def update_user_profile(self, user_id: str, name: str | None, email: str | None) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE users SET
                  name  = COALESCE(%s, name),
                  email = COALESCE(%s, email)
                WHERE id = %s
                RETURNING id, phone, email, name, role, tier, verified
                """,
                (name, email, user_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

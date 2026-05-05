"""Repositories for subscription tables: subscriptions, notification_log."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...common.time import iso, utc_now


class SQLiteSubscriptionsRepository:
    """SQLite-backed repository for subscriptions and notification_log."""

    def __init__(self, connect_fn) -> None:
        self._connect = connect_fn

    def add_subscription(
        self,
        telegram_id: str,
        room_no: str,
        target_serial: int,
        look_ahead: int,
        hearing_date: str | None = None,
        contact_type: str = "telegram",
        display_name: str | None = None,
        phone: str | None = None,
    ) -> int:
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO subscriptions(
                  telegram_id, room_no, target_serial, look_ahead, active, created_at,
                  hearing_date, contact_type, display_name, phone
                )
                VALUES(?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    room_no,
                    target_serial,
                    look_ahead,
                    iso(utc_now()),
                    hearing_date,
                    contact_type,
                    display_name,
                    phone,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def remove_subscription(self, telegram_id: str, room_no: str) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE subscriptions SET active=0 WHERE telegram_id=? AND room_no=?",
                (telegram_id, room_no),
            )

    def remove_whatsapp_subscription(self, phone: str, room_no: str) -> int:
        with self._connect() as con:
            cur = con.execute(
                "UPDATE subscriptions SET active=0 WHERE phone=? AND room_no=? AND contact_type='whatsapp' AND active=1",
                (phone, room_no),
            )
            return cur.rowcount

    def list_active_subscriptions(self, today: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as con:
            if today:
                rows = con.execute(
                    "SELECT * FROM subscriptions WHERE active=1"
                    " AND (hearing_date IS NULL OR hearing_date=?)",
                    (today,),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM subscriptions WHERE active=1").fetchall()
        return [dict(r) for r in rows]

    def update_last_notified_serial(self, sub_id: int, serial: int) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE subscriptions SET last_notified_serial=? WHERE id=?",
                (serial, sub_id),
            )

    def list_user_subscriptions(self, telegram_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM subscriptions WHERE telegram_id=? AND active=1",
                (telegram_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def was_notified_today(self, sub_id: int) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM notification_log WHERE sub_id=? AND DATE(sent_at)=?",
                (sub_id, today),
            ).fetchone()
        return row is not None

    def log_notification(self, sub_id: int, payload: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO notification_log(sub_id, sent_at, payload) VALUES(?, ?, ?)",
                (sub_id, iso(utc_now()), payload),
            )

    def mark_alerted(self, sub_id: int) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE subscriptions SET alerted_at=? WHERE id=?",
                (iso(utc_now()), sub_id),
            )

    def mark_reminder_sent(self, sub_id: int) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE subscriptions SET reminder_sent=1 WHERE id=?",
                (sub_id,),
            )

    def deactivate_subscription(self, sub_id: int) -> None:
        with self._connect() as con:
            con.execute("UPDATE subscriptions SET active=0 WHERE id=?", (sub_id,))

    def list_active_subscriptions_for_room(self, room_no: str, today: str) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT * FROM subscriptions WHERE active=1 AND room_no=?"
                " AND (hearing_date IS NULL OR hearing_date=?)",
                (room_no, today),
            ).fetchall()
        return [dict(r) for r in rows]


class PostgresSubscriptionsRepository:
    """PostgreSQL-backed repository for subscriptions and notification_log."""

    def __init__(self, cursor_ctx) -> None:
        self._cursor = cursor_ctx

    def add_subscription(
        self,
        telegram_id: str,
        room_no: str,
        target_serial: int,
        look_ahead: int,
        hearing_date: str | None = None,
        contact_type: str = "telegram",
        display_name: str | None = None,
        phone: str | None = None,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscriptions(
                  telegram_id, room_no, target_serial, look_ahead, active, created_at,
                  hearing_date, contact_type, display_name, phone
                )
                VALUES(%s, %s, %s, %s, 1, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    telegram_id,
                    room_no,
                    target_serial,
                    look_ahead,
                    iso(utc_now()),
                    hearing_date,
                    contact_type,
                    display_name,
                    phone,
                ),
            )
            return cur.fetchone()["id"]  # type: ignore[index]

    def remove_subscription(self, telegram_id: str, room_no: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE subscriptions SET active=0 WHERE telegram_id=%s AND room_no=%s",
                (telegram_id, room_no),
            )

    def remove_whatsapp_subscription(self, phone: str, room_no: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE subscriptions SET active=0 WHERE phone=%s AND room_no=%s AND contact_type='whatsapp' AND active=1",
                (phone, room_no),
            )
            return cur.rowcount

    def list_active_subscriptions(self, today: str | None = None) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            if today:
                cur.execute(
                    "SELECT * FROM subscriptions WHERE active=1 AND (hearing_date IS NULL OR hearing_date=%s)",
                    (today,),
                )
            else:
                cur.execute("SELECT * FROM subscriptions WHERE active=1")
            return [dict(r) for r in cur.fetchall()]

    def update_last_notified_serial(self, sub_id: int, serial: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE subscriptions SET last_notified_serial=%s WHERE id=%s",
                (serial, sub_id),
            )

    def list_user_subscriptions(self, telegram_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM subscriptions WHERE telegram_id=%s AND active=1",
                (telegram_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def was_notified_today(self, sub_id: int) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM notification_log WHERE sub_id=%s AND sent_at::date=CURRENT_DATE",
                (sub_id,),
            )
            return cur.fetchone() is not None

    def log_notification(self, sub_id: int, payload: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO notification_log(sub_id, sent_at, payload) VALUES(%s, %s, %s)",
                (sub_id, iso(utc_now()), payload),
            )

    def mark_alerted(self, sub_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE subscriptions SET alerted_at=%s WHERE id=%s", (iso(utc_now()), sub_id)
            )

    def mark_reminder_sent(self, sub_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE subscriptions SET reminder_sent=1 WHERE id=%s", (sub_id,))

    def deactivate_subscription(self, sub_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE subscriptions SET active=0 WHERE id=%s", (sub_id,))

    def list_active_subscriptions_for_room(self, room_no: str, today: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM subscriptions WHERE active=1 AND room_no=%s AND (hearing_date IS NULL OR hearing_date=%s)",
                (room_no, today),
            )
            return [dict(r) for r in cur.fetchall()]

"""SQLAlchemy-based subscriptions repository.

Single implementation for both SQLite and PostgreSQL.
Replaces SQLiteSubscriptionsRepository + PostgresSubscriptionsRepository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ...common.time import iso, utc_now
from ..models import NotificationLog, Subscription


class SQLAlchemySubscriptionsRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        with Session(self._engine) as session:
            sub = Subscription(
                telegram_id=telegram_id,
                room_no=room_no,
                target_serial=target_serial,
                look_ahead=look_ahead,
                active=1,
                created_at=iso(utc_now()),
                hearing_date=hearing_date,
                contact_type=contact_type,
                display_name=display_name,
                phone=phone,
            )
            session.add(sub)
            session.flush()
            sub_id = sub.id
            session.commit()
        return sub_id  # type: ignore[return-value]

    def remove_subscription(self, telegram_id: str, room_no: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(Subscription)
                .where(Subscription.telegram_id == telegram_id, Subscription.room_no == room_no)
                .values(active=0)
            )
            session.commit()

    def remove_whatsapp_subscription(self, phone: str, room_no: str) -> int:
        with Session(self._engine) as session:
            result = session.execute(
                update(Subscription)
                .where(
                    Subscription.phone == phone,
                    Subscription.room_no == room_no,
                    Subscription.contact_type == "whatsapp",
                    Subscription.active == 1,
                )
                .values(active=0)
            )
            session.commit()
        return result.rowcount

    def list_active_subscriptions(self, today: str | None = None) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            q = select(Subscription).where(Subscription.active == 1)
            if today:
                q = q.where(
                    (Subscription.hearing_date == None) | (Subscription.hearing_date == today)  # noqa: E711
                )
            rows = session.scalars(q).all()
        return [_sub_to_dict(r) for r in rows]

    def update_last_notified_serial(self, sub_id: int, serial: int) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(Subscription)
                .where(Subscription.id == sub_id)
                .values(last_notified_serial=serial)
            )
            session.commit()

    def list_user_subscriptions(self, telegram_id: str) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(Subscription).where(
                    Subscription.telegram_id == telegram_id, Subscription.active == 1
                )
            ).all()
        return [_sub_to_dict(r) for r in rows]

    def was_notified_today(self, sub_id: int) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with Session(self._engine) as session:
            row = session.scalar(
                select(NotificationLog)
                .where(
                    NotificationLog.sub_id == sub_id,
                    NotificationLog.sent_at.like(f"{today}%"),
                )
                .limit(1)
            )
        return row is not None

    def log_notification(self, sub_id: int, payload: str) -> None:
        with Session(self._engine) as session:
            session.add(NotificationLog(sub_id=sub_id, sent_at=iso(utc_now()), payload=payload))
            session.commit()

    def mark_alerted(self, sub_id: int) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(Subscription)
                .where(Subscription.id == sub_id)
                .values(alerted_at=iso(utc_now()))
            )
            session.commit()

    def mark_reminder_sent(self, sub_id: int) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(Subscription).where(Subscription.id == sub_id).values(reminder_sent=1)
            )
            session.commit()

    def deactivate_subscription(self, sub_id: int) -> None:
        with Session(self._engine) as session:
            session.execute(update(Subscription).where(Subscription.id == sub_id).values(active=0))
            session.commit()

    def list_active_subscriptions_for_room(self, room_no: str, today: str) -> list[dict]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(Subscription).where(
                    Subscription.active == 1,
                    Subscription.room_no == room_no,
                    (Subscription.hearing_date == None) | (Subscription.hearing_date == today),  # noqa: E711
                )
            ).all()
        return [_sub_to_dict(r) for r in rows]


def _sub_to_dict(r: Subscription) -> dict:
    return {
        "id": r.id,
        "telegram_id": r.telegram_id,
        "room_no": r.room_no,
        "target_serial": r.target_serial,
        "look_ahead": r.look_ahead,
        "active": r.active,
        "created_at": r.created_at,
        "hearing_date": r.hearing_date,
        "contact_type": r.contact_type,
        "last_notified_serial": r.last_notified_serial,
        "display_name": r.display_name,
        "phone": r.phone,
        "alerted_at": r.alerted_at,
        "reminder_sent": r.reminder_sent,
    }

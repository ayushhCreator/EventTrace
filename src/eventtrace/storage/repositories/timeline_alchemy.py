"""SQLAlchemy-based timeline repository.

Single implementation for both SQLite and PostgreSQL.
Replaces SQLiteTimelineRepository + PostgresTimelineRepository.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ...common.time import iso, utc_now
from ..models import CaseSnapshot, CaseTimelineEvent, TrackedCase


class SQLAlchemyTimelineRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_snapshot(self, case_ref: str, list_date: str, data_json: str, hash_val: str) -> bool:
        now = iso(utc_now())
        with Session(self._engine) as session:
            obj = session.scalar(
                select(CaseSnapshot).where(
                    CaseSnapshot.case_ref == case_ref, CaseSnapshot.list_date == list_date
                )
            )
            if obj and obj.hash == hash_val:
                return False
            if obj:
                obj.data_json = data_json
                obj.hash = hash_val
                obj.created_at = now
            else:
                session.add(CaseSnapshot(
                    case_ref=case_ref, list_date=list_date,
                    data_json=data_json, hash=hash_val, created_at=now,
                ))
            session.commit()
        return True

    def get_last_snapshot(self, case_ref: str) -> dict | None:
        with Session(self._engine) as session:
            obj = session.scalar(
                select(CaseSnapshot)
                .where(CaseSnapshot.case_ref == case_ref)
                .order_by(CaseSnapshot.list_date.desc())
                .limit(1)
            )
            if not obj:
                return None
            return {
                "id": obj.id, "case_ref": obj.case_ref, "list_date": obj.list_date,
                "data_json": obj.data_json, "hash": obj.hash, "created_at": obj.created_at,
            }

    def insert_timeline_event(
        self,
        user_id: str,
        case_ref: str,
        event_type: str,
        event_date: str,
        change_summary: str | None = None,
    ) -> None:
        with Session(self._engine) as session:
            session.add(CaseTimelineEvent(
                user_id=user_id,
                case_ref=case_ref,
                event_type=event_type,
                event_date=event_date,
                change_summary=change_summary,
                created_at=iso(utc_now()),
            ))
            session.commit()

    def get_timeline(self, user_id: str, case_ref: str, limit: int = 50) -> list[dict]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(CaseTimelineEvent)
                .where(CaseTimelineEvent.user_id == user_id, CaseTimelineEvent.case_ref == case_ref)
                .order_by(CaseTimelineEvent.event_date.desc(), CaseTimelineEvent.id.desc())
                .limit(limit)
            ).all()
        return [
            {
                "id": r.id, "user_id": r.user_id, "case_ref": r.case_ref,
                "event_type": r.event_type, "event_date": r.event_date,
                "change_summary": r.change_summary, "created_at": r.created_at,
            }
            for r in rows
        ]

    def get_all_tracked_case_refs(self) -> list[str]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(TrackedCase.case_ref).distinct()
            ).scalars().all()
        return list(rows)

    def get_users_tracking(self, case_ref: str) -> list[str]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(TrackedCase.user_id).distinct().where(TrackedCase.case_ref == case_ref)
            ).scalars().all()
        return list(rows)

    def has_causelist_alert_today(self, user_id: str, case_ref: str, event_date: str) -> bool:
        with Session(self._engine) as session:
            row = session.scalar(
                select(CaseTimelineEvent)
                .where(
                    CaseTimelineEvent.user_id == user_id,
                    CaseTimelineEvent.case_ref == case_ref,
                    CaseTimelineEvent.event_type == "case_in_causelist",
                    CaseTimelineEvent.event_date == event_date,
                )
                .limit(1)
            )
        return row is not None

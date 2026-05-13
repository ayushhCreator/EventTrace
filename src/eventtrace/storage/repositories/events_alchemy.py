"""SQLAlchemy-based events repository.

Single implementation for both SQLite and PostgreSQL.
Replaces SQLiteEventsRepository + PostgresEventsRepository.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ...common.time import iso
from ...domain.models import EventTrace as EventTraceDomain
from ..models import (
    CurrentState,
    EventTrace as EventTraceORM,
    FieldState,
    MonitorState,
    VcZoomLink,
)


def _is_pg(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


class SQLAlchemyEventsRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with Session(self._engine) as session:
            obj = session.get(CurrentState, court_id)
            if obj:
                obj.data_json = payload
                obj.last_seen_time = iso(seen_time)
            else:
                session.add(
                    CurrentState(
                        court_id=court_id, data_json=payload, last_seen_time=iso(seen_time)
                    )
                )
            session.commit()

    def get_field_state(self, court_id: str, field_name: str) -> dict | None:
        with Session(self._engine) as session:
            obj = session.get(FieldState, (court_id, field_name))
            if not obj:
                return None
            return {
                "court_id": obj.court_id,
                "field_name": obj.field_name,
                "value": obj.value,
                "start_time": obj.start_time,
                "last_seen_time": obj.last_seen_time,
            }

    def upsert_field_state(
        self,
        court_id: str,
        field_name: str,
        value: str | None,
        start_time: datetime,
        last_seen_time: datetime,
    ) -> None:
        with Session(self._engine) as session:
            obj = session.get(FieldState, (court_id, field_name))
            if obj:
                obj.value = value
                obj.start_time = iso(start_time)
                obj.last_seen_time = iso(last_seen_time)
            else:
                session.add(
                    FieldState(
                        court_id=court_id,
                        field_name=field_name,
                        value=value,
                        start_time=iso(start_time),
                        last_seen_time=iso(last_seen_time),
                    )
                )
            session.commit()

    def touch_field_state(self, court_id: str, field_name: str, last_seen_time: datetime) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(FieldState)
                .where(FieldState.court_id == court_id, FieldState.field_name == field_name)
                .values(last_seen_time=iso(last_seen_time))
            )
            session.commit()

    def insert_event_trace(self, trace: EventTraceDomain, observed_time: datetime) -> None:
        with Session(self._engine) as session:
            session.add(
                EventTraceORM(
                    court_id=trace.court_id,
                    field_name=trace.field_name,
                    old_value=trace.old_value,
                    new_value=trace.new_value,
                    start_time=iso(trace.start_time),
                    end_time=iso(trace.end_time),
                    duration_seconds=trace.duration_seconds,
                    observed_time=iso(observed_time),
                )
            )
            session.commit()

    def insert_change(self, change: EventTraceDomain, observed_time: datetime) -> None:
        self.insert_event_trace(change, observed_time=observed_time)

    def list_current_state(self) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            rows = session.scalars(select(CurrentState).order_by(CurrentState.court_id)).all()
        return [
            {
                "court_id": r.court_id,
                "data": json.loads(r.data_json),
                "last_seen_time": r.last_seen_time,
            }
            for r in rows
        ]

    def list_event_traces(
        self, limit: int = 200, court_id: str | None = None
    ) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            q = select(EventTraceORM).order_by(EventTraceORM.observed_time.desc()).limit(limit)
            if court_id:
                q = q.where(EventTraceORM.court_id == court_id)
            rows = session.scalars(q).all()
        return [
            {
                "id": r.id,
                "court_id": r.court_id,
                "field_name": r.field_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "start_time": r.start_time,
                "end_time": r.end_time,
                "duration_seconds": r.duration_seconds,
                "observed_time": r.observed_time,
            }
            for r in rows
        ]

    def list_changes(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
        return self.list_event_traces(limit=limit, court_id=court_id)

    def list_field_state(self, court_id: str) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(FieldState)
                .where(FieldState.court_id == court_id)
                .order_by(FieldState.field_name)
            ).all()
        return [
            {
                "court_id": r.court_id,
                "field_name": r.field_name,
                "value": r.value,
                "start_time": r.start_time,
                "last_seen_time": r.last_seen_time,
            }
            for r in rows
        ]

    def list_field_names(self, court_id: str) -> set[str]:
        with Session(self._engine) as session:
            rows = (
                session.execute(
                    select(FieldState.field_name).where(FieldState.court_id == court_id)
                )
                .scalars()
                .all()
            )
        return set(rows)

    def list_absent_court_ids(self) -> list[str]:
        with Session(self._engine) as session:
            rows = (
                session.execute(
                    select(FieldState.court_id).where(
                        FieldState.field_name == "__present__", FieldState.value == "0"
                    )
                )
                .scalars()
                .all()
            )
        return list(rows)

    def list_serial_start_times(self) -> dict[str, str]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(FieldState.court_id, FieldState.start_time).where(
                    FieldState.field_name == "cause_list_sr_no"
                )
            ).all()
        return {r.court_id: r.start_time for r in rows}

    def known_courts(self) -> set[str]:
        with Session(self._engine) as session:
            rows = session.execute(select(CurrentState.court_id)).scalars().all()
        return set(rows)

    def list_active_dates(self) -> list[str]:
        with Session(self._engine) as session:
            if _is_pg(self._engine):
                rows = session.execute(
                    text(
                        "SELECT DISTINCT (observed_time::timestamptz AT TIME ZONE 'Asia/Kolkata')::date AS d "
                        "FROM event_trace ORDER BY d DESC"
                    )
                ).all()
                return [str(r.d) for r in rows]
            else:
                rows = session.execute(
                    text(
                        "SELECT DISTINCT DATE(observed_time, '+5 hours', '30 minutes') AS d "
                        "FROM event_trace ORDER BY d DESC"
                    )
                ).all()
                return [r.d for r in rows]

    def list_day_activity(self, date_str: str) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            if _is_pg(self._engine):
                rows = (
                    session.execute(
                        text("""
                    SELECT
                      court_id,
                      SUM(CASE WHEN field_name != '__present__' THEN 1 ELSE 0 END) AS change_count,
                      string_agg(
                        DISTINCT CASE WHEN field_name != '__present__' THEN field_name ELSE NULL END,
                        ','
                      ) AS fields_changed,
                      MIN(observed_time) AS first_event,
                      MAX(observed_time) AS last_event,
                      MAX(CASE WHEN field_name='__present__' AND new_value='1' THEN 1 ELSE 0 END) AS appeared,
                      MAX(CASE WHEN field_name='__present__' AND new_value='0' THEN 1 ELSE 0 END) AS disappeared
                    FROM event_trace
                    WHERE (observed_time::timestamptz AT TIME ZONE 'Asia/Kolkata')::date = :d::date
                    GROUP BY court_id
                    ORDER BY court_id
                """),
                        {"d": date_str},
                    )
                    .mappings()
                    .all()
                )
            else:
                rows = (
                    session.execute(
                        text("""
                    SELECT
                      court_id,
                      SUM(CASE WHEN field_name != '__present__' THEN 1 ELSE 0 END) AS change_count,
                      GROUP_CONCAT(
                        DISTINCT CASE WHEN field_name != '__present__' THEN field_name END
                      ) AS fields_changed,
                      MIN(observed_time) AS first_event,
                      MAX(observed_time) AS last_event,
                      MAX(CASE WHEN field_name='__present__' AND new_value='1' THEN 1 ELSE 0 END) AS appeared,
                      MAX(CASE WHEN field_name='__present__' AND new_value='0' THEN 1 ELSE 0 END) AS disappeared
                    FROM event_trace
                    WHERE DATE(observed_time, '+5 hours', '30 minutes') = :d
                    GROUP BY court_id
                    ORDER BY court_id
                """),
                        {"d": date_str},
                    )
                    .mappings()
                    .all()
                )
        return [dict(r) for r in rows]

    def set_monitor_state(self, key: str, value: str) -> None:
        with Session(self._engine) as session:
            obj = session.get(MonitorState, key)
            if obj:
                obj.value = value
            else:
                session.add(MonitorState(key=key, value=value))
            session.commit()

    def get_monitor_state(self, key: str) -> str | None:
        with Session(self._engine) as session:
            obj = session.get(MonitorState, key)
        return obj.value if obj else None

    def upsert_vc_zoom_link(
        self, date: str, room_no: str, zoom_url: str, scraped_at: datetime
    ) -> None:
        with Session(self._engine) as session:
            obj = session.get(VcZoomLink, (date, room_no))
            if obj:
                obj.zoom_url = zoom_url
                obj.scraped_at = iso(scraped_at)
            else:
                session.add(
                    VcZoomLink(
                        date=date, room_no=room_no, zoom_url=zoom_url, scraped_at=iso(scraped_at)
                    )
                )
            session.commit()

    def get_vc_zoom_links(self, date: str) -> dict[str, str]:
        with Session(self._engine) as session:
            rows = session.scalars(select(VcZoomLink).where(VcZoomLink.date == date)).all()
        return {r.room_no: r.zoom_url for r in rows}

    def list_vc_dates(self) -> list[str]:
        with Session(self._engine) as session:
            rows = (
                session.execute(select(VcZoomLink.date).distinct().order_by(VcZoomLink.date.desc()))
                .scalars()
                .all()
            )
        return list(rows)

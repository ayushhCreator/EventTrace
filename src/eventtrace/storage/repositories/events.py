"""Repositories for event-tracing tables: current_state, field_state, event_trace."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ...common.time import iso
from ...domain.models import EventTrace


class SQLiteEventsRepository:
    """SQLite-backed repository for current_state, field_state, and event_trace."""

    def __init__(self, connect_fn) -> None:
        self._connect = connect_fn

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO current_state(court_id, data_json, last_seen_time)
                VALUES(?, ?, ?)
                ON CONFLICT(court_id) DO UPDATE SET
                  data_json=excluded.data_json,
                  last_seen_time=excluded.last_seen_time
                """,
                (court_id, payload, iso(seen_time)),
            )

    def get_field_state(self, court_id: str, field_name: str):
        with self._connect() as con:
            cur = con.execute(
                "SELECT * FROM field_state WHERE court_id=? AND field_name=?",
                (court_id, field_name),
            )
            return cur.fetchone()

    def upsert_field_state(
        self,
        court_id: str,
        field_name: str,
        value: str | None,
        start_time: datetime,
        last_seen_time: datetime,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO field_state(court_id, field_name, value, start_time, last_seen_time)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(court_id, field_name) DO UPDATE SET
                  value=excluded.value,
                  start_time=excluded.start_time,
                  last_seen_time=excluded.last_seen_time
                """,
                (court_id, field_name, value, iso(start_time), iso(last_seen_time)),
            )

    def touch_field_state(self, court_id: str, field_name: str, last_seen_time: datetime) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE field_state SET last_seen_time=? WHERE court_id=? AND field_name=?",
                (iso(last_seen_time), court_id, field_name),
            )

    def insert_event_trace(self, trace: EventTrace, observed_time: datetime) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO event_trace(
                  court_id, field_name, old_value, new_value,
                  start_time, end_time, duration_seconds, observed_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.court_id,
                    trace.field_name,
                    trace.old_value,
                    trace.new_value,
                    iso(trace.start_time),
                    iso(trace.end_time),
                    trace.duration_seconds,
                    iso(observed_time),
                ),
            )

    def insert_change(self, change: EventTrace, observed_time: datetime) -> None:
        self.insert_event_trace(change, observed_time=observed_time)

    def list_current_state(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT court_id, data_json, last_seen_time FROM current_state ORDER BY court_id ASC"
            ).fetchall()
        return [
            {
                "court_id": r["court_id"],
                "data": json.loads(r["data_json"]),
                "last_seen_time": r["last_seen_time"],
            }
            for r in rows
        ]

    def list_event_traces(
        self, limit: int = 200, court_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = """
          SELECT id, court_id, field_name, old_value, new_value,
                 start_time, end_time, duration_seconds, observed_time
          FROM event_trace
        """
        params: list[Any] = []
        where = ""
        if court_id:
            where = " WHERE court_id=? "
            params.append(court_id)
        query += where + " ORDER BY observed_time DESC LIMIT ?"
        params.append(limit)
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def list_changes(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
        return self.list_event_traces(limit=limit, court_id=court_id)

    def list_field_state(self, court_id: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT court_id, field_name, value, start_time, last_seen_time
                FROM field_state
                WHERE court_id=?
                ORDER BY field_name ASC
                """,
                (court_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_field_names(self, court_id: str) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT field_name FROM field_state WHERE court_id=?",
                (court_id,),
            ).fetchall()
        return {r["field_name"] for r in rows}

    def list_absent_court_ids(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT court_id FROM field_state WHERE field_name='__present__' AND value='0'"
            ).fetchall()
        return [r["court_id"] for r in rows]

    def list_serial_start_times(self) -> dict[str, str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT court_id, start_time FROM field_state WHERE field_name='cause_list_sr_no'"
            ).fetchall()
        return {r["court_id"]: r["start_time"] for r in rows}

    def known_courts(self) -> set[str]:
        with self._connect() as con:
            rows = con.execute("SELECT court_id FROM current_state").fetchall()
        return {r["court_id"] for r in rows}

    def list_active_dates(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT DATE(observed_time, '+5 hours', '30 minutes') AS d
                FROM event_trace
                ORDER BY d DESC
                """
            ).fetchall()
        return [r["d"] for r in rows]

    def list_day_activity(self, date_str: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                """
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
                WHERE DATE(observed_time, '+5 hours', '30 minutes') = ?
                GROUP BY court_id
                ORDER BY court_id
                """,
                (date_str,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_monitor_state(self, key: str, value: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO monitor_state(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_monitor_state(self, key: str) -> str | None:
        with self._connect() as con:
            row = con.execute("SELECT value FROM monitor_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def upsert_vc_zoom_link(
        self, date: str, room_no: str, zoom_url: str, scraped_at: datetime
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO vc_zoom_link(date, room_no, zoom_url, scraped_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(date, room_no) DO UPDATE SET
                  zoom_url=excluded.zoom_url,
                  scraped_at=excluded.scraped_at
                """,
                (date, room_no, zoom_url, iso(scraped_at)),
            )

    def get_vc_zoom_links(self, date: str) -> dict[str, str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT room_no, zoom_url FROM vc_zoom_link WHERE date=?",
                (date,),
            ).fetchall()
        return {r["room_no"]: r["zoom_url"] for r in rows}

    def list_vc_dates(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT date FROM vc_zoom_link ORDER BY date DESC"
            ).fetchall()
        return [r["date"] for r in rows]


class PostgresEventsRepository:
    """PostgreSQL-backed repository for current_state, field_state, and event_trace."""

    def __init__(self, cursor_ctx) -> None:
        self._cursor = cursor_ctx

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO current_state(court_id, data_json, last_seen_time)
                VALUES(%s, %s, %s)
                ON CONFLICT(court_id) DO UPDATE SET
                  data_json=EXCLUDED.data_json,
                  last_seen_time=EXCLUDED.last_seen_time
                """,
                (court_id, payload, iso(seen_time)),
            )

    def get_field_state(self, court_id: str, field_name: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM field_state WHERE court_id=%s AND field_name=%s",
                (court_id, field_name),
            )
            return cur.fetchone()

    def upsert_field_state(
        self,
        court_id: str,
        field_name: str,
        value: str | None,
        start_time: datetime,
        last_seen_time: datetime,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO field_state(court_id, field_name, value, start_time, last_seen_time)
                VALUES(%s, %s, %s, %s, %s)
                ON CONFLICT(court_id, field_name) DO UPDATE SET
                  value=EXCLUDED.value,
                  start_time=EXCLUDED.start_time,
                  last_seen_time=EXCLUDED.last_seen_time
                """,
                (court_id, field_name, value, iso(start_time), iso(last_seen_time)),
            )

    def touch_field_state(self, court_id: str, field_name: str, last_seen_time: datetime) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE field_state SET last_seen_time=%s WHERE court_id=%s AND field_name=%s",
                (iso(last_seen_time), court_id, field_name),
            )

    def insert_event_trace(self, trace: EventTrace, observed_time: datetime) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO event_trace(
                  court_id, field_name, old_value, new_value,
                  start_time, end_time, duration_seconds, observed_time
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    trace.court_id,
                    trace.field_name,
                    trace.old_value,
                    trace.new_value,
                    iso(trace.start_time),
                    iso(trace.end_time),
                    trace.duration_seconds,
                    iso(observed_time),
                ),
            )

    def insert_change(self, change: EventTrace, observed_time: datetime) -> None:
        self.insert_event_trace(change, observed_time=observed_time)

    def list_current_state(self) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT court_id, data_json, last_seen_time FROM current_state ORDER BY court_id ASC"
            )
            rows = cur.fetchall()
        return [
            {
                "court_id": r["court_id"],
                "data": json.loads(r["data_json"]),
                "last_seen_time": r["last_seen_time"],
            }
            for r in rows
        ]

    def list_event_traces(
        self, limit: int = 200, court_id: str | None = None
    ) -> list[dict[str, Any]]:
        if court_id:
            q = "SELECT * FROM event_trace WHERE court_id=%s ORDER BY observed_time DESC LIMIT %s"
            params: tuple = (court_id, limit)
        else:
            q = "SELECT * FROM event_trace ORDER BY observed_time DESC LIMIT %s"
            params = (limit,)
        with self._cursor() as cur:
            cur.execute(q, params)
            return [dict(r) for r in cur.fetchall()]

    def list_changes(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
        return self.list_event_traces(limit=limit, court_id=court_id)

    def list_field_state(self, court_id: str) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM field_state WHERE court_id=%s ORDER BY field_name ASC",
                (court_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def list_field_names(self, court_id: str) -> set[str]:
        with self._cursor() as cur:
            cur.execute("SELECT field_name FROM field_state WHERE court_id=%s", (court_id,))
            return {r["field_name"] for r in cur.fetchall()}

    def list_absent_court_ids(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT court_id FROM field_state WHERE field_name='__present__' AND value='0'"
            )
            return [r["court_id"] for r in cur.fetchall()]

    def list_serial_start_times(self) -> dict[str, str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT court_id, start_time FROM field_state WHERE field_name='cause_list_sr_no'"
            )
            return {r["court_id"]: r["start_time"] for r in cur.fetchall()}

    def known_courts(self) -> set[str]:
        with self._cursor() as cur:
            cur.execute("SELECT court_id FROM current_state")
            return {r["court_id"] for r in cur.fetchall()}

    def list_active_dates(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT (observed_time::timestamptz AT TIME ZONE 'Asia/Kolkata')::date AS d
                FROM event_trace
                ORDER BY d DESC
                """
            )
            return [str(r["d"]) for r in cur.fetchall()]

    def list_day_activity(self, date_str: str) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                """
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
                WHERE (observed_time::timestamptz AT TIME ZONE 'Asia/Kolkata')::date = %s::date
                GROUP BY court_id
                ORDER BY court_id
                """,
                (date_str,),
            )
            return [dict(r) for r in cur.fetchall()]

    def set_monitor_state(self, key: str, value: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO monitor_state(key, value) VALUES(%s, %s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (key, value),
            )

    def get_monitor_state(self, key: str) -> str | None:
        with self._cursor() as cur:
            cur.execute("SELECT value FROM monitor_state WHERE key=%s", (key,))
            row = cur.fetchone()
        return row["value"] if row else None

    def upsert_vc_zoom_link(
        self, date: str, room_no: str, zoom_url: str, scraped_at: datetime
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO vc_zoom_link(date, room_no, zoom_url, scraped_at)
                VALUES(%s, %s, %s, %s)
                ON CONFLICT(date, room_no) DO UPDATE SET
                  zoom_url=EXCLUDED.zoom_url,
                  scraped_at=EXCLUDED.scraped_at
                """,
                (date, room_no, zoom_url, iso(scraped_at)),
            )

    def get_vc_zoom_links(self, date: str) -> dict[str, str]:
        with self._cursor() as cur:
            cur.execute("SELECT room_no, zoom_url FROM vc_zoom_link WHERE date=%s", (date,))
            return {r["room_no"]: r["zoom_url"] for r in cur.fetchall()}

    def list_vc_dates(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute("SELECT DISTINCT date FROM vc_zoom_link ORDER BY date DESC")
            return [r["date"] for r in cur.fetchall()]

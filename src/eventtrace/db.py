from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    # Python 3.11+ supports Z; keep general.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EventTrace:
    court_id: str
    field_name: str
    old_value: str | None
    new_value: str | None
    start_time: datetime
    end_time: datetime

    @property
    def duration_seconds(self) -> int:
        return max(0, int((self.end_time - self.start_time).total_seconds()))


class DB:
    def __init__(self, path: str) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def ensure_schema(self) -> None:
        with self.connect() as con:
            # Lightweight migration: rename legacy `change_history` -> `event_trace`
            existing_tables = {
                r["name"]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "change_history" in existing_tables and "event_trace" not in existing_tables:
                con.execute("ALTER TABLE change_history RENAME TO event_trace;")

            # Drop legacy indexes (if present); recreated below with new names.
            con.execute("DROP INDEX IF EXISTS idx_change_history_time;")
            con.execute("DROP INDEX IF EXISTS idx_change_history_court;")

            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS current_state (
                  court_id TEXT PRIMARY KEY,
                  data_json TEXT NOT NULL,
                  last_seen_time TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS field_state (
                  court_id TEXT NOT NULL,
                  field_name TEXT NOT NULL,
                  value TEXT,
                  start_time TEXT NOT NULL,
                  last_seen_time TEXT NOT NULL,
                  PRIMARY KEY (court_id, field_name)
                );

                CREATE TABLE IF NOT EXISTS event_trace (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  court_id TEXT NOT NULL,
                  field_name TEXT NOT NULL,
                  old_value TEXT,
                  new_value TEXT,
                  start_time TEXT NOT NULL,
                  end_time TEXT NOT NULL,
                  duration_seconds INTEGER NOT NULL,
                  observed_time TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_event_trace_time
                  ON event_trace(observed_time DESC);
                CREATE INDEX IF NOT EXISTS idx_event_trace_court
                  ON event_trace(court_id, observed_time DESC);
                """
            )

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with self.connect() as con:
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

    def get_field_state(self, court_id: str, field_name: str) -> sqlite3.Row | None:
        with self.connect() as con:
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
        with self.connect() as con:
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
        with self.connect() as con:
            con.execute(
                """
                UPDATE field_state SET last_seen_time=?
                WHERE court_id=? AND field_name=?
                """,
                (iso(last_seen_time), court_id, field_name),
            )

    def insert_event_trace(self, trace: EventTrace, observed_time: datetime) -> None:
        with self.connect() as con:
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
        # Backward-compatible alias
        self.insert_event_trace(change, observed_time=observed_time)

    def list_current_state(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT court_id, data_json, last_seen_time FROM current_state ORDER BY court_id ASC"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "court_id": r["court_id"],
                    "data": json.loads(r["data_json"]),
                    "last_seen_time": r["last_seen_time"],
                }
            )
        return out

    def list_event_traces(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
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
        with self.connect() as con:
            rows = con.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def list_changes(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
        # Backward-compatible alias
        return self.list_event_traces(limit=limit, court_id=court_id)

    def list_field_state(self, court_id: str) -> list[dict[str, Any]]:
        with self.connect() as con:
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
        with self.connect() as con:
            rows = con.execute(
                "SELECT field_name FROM field_state WHERE court_id=?",
                (court_id,),
            ).fetchall()
        return {r["field_name"] for r in rows}

    def known_courts(self) -> set[str]:
        with self.connect() as con:
            rows = con.execute("SELECT court_id FROM current_state").fetchall()
        return {r["court_id"] for r in rows}

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


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

                CREATE TABLE IF NOT EXISTS vc_zoom_link (
                  date       TEXT NOT NULL,
                  room_no    TEXT NOT NULL,
                  zoom_url   TEXT NOT NULL,
                  scraped_at TEXT NOT NULL,
                  PRIMARY KEY (date, room_no)
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                  id           INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id  TEXT NOT NULL,
                  room_no      TEXT NOT NULL,
                  target_serial INTEGER NOT NULL,
                  look_ahead   INTEGER NOT NULL DEFAULT 5,
                  active       INTEGER NOT NULL DEFAULT 1,
                  created_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_log (
                  id        INTEGER PRIMARY KEY AUTOINCREMENT,
                  sub_id    INTEGER REFERENCES subscriptions(id),
                  sent_at   TEXT NOT NULL,
                  payload   TEXT NOT NULL
                );
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

    def list_absent_court_ids(self) -> list[str]:
        """Returns court_ids where __present__ is currently '0' (left the board)."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT court_id FROM field_state WHERE field_name='__present__' AND value='0'"
            ).fetchall()
        return [r["court_id"] for r in rows]

    def list_serial_start_times(self) -> dict[str, str]:
        """Returns {court_id: start_time ISO} for the current cause_list_sr_no of every court."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT court_id, start_time FROM field_state WHERE field_name='cause_list_sr_no'"
            ).fetchall()
        return {r["court_id"]: r["start_time"] for r in rows}

    def known_courts(self) -> set[str]:
        with self.connect() as con:
            rows = con.execute("SELECT court_id FROM current_state").fetchall()
        return {r["court_id"] for r in rows}

    def list_active_dates(self) -> list[str]:
        """Distinct dates (YYYY-MM-DD, IST offset +05:30) that have event_trace rows."""
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT DATE(observed_time, '+5 hours', '30 minutes') AS d
                FROM event_trace
                ORDER BY d DESC
                """
            ).fetchall()
        return [r["d"] for r in rows]

    def list_day_activity(self, date_str: str) -> list[dict[str, Any]]:
        """Per-court summary of activity on a given date (YYYY-MM-DD local IST)."""
        with self.connect() as con:
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

    # ── VC Zoom Links ────────────────────────────────────────────────────────

    def upsert_vc_zoom_link(self, date: str, room_no: str, zoom_url: str, scraped_at: datetime) -> None:
        with self.connect() as con:
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
        """Returns {room_no: zoom_url} for given date (YYYY-MM-DD IST)."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT room_no, zoom_url FROM vc_zoom_link WHERE date=?",
                (date,),
            ).fetchall()
        return {r["room_no"]: r["zoom_url"] for r in rows}

    # ── Subscriptions ────────────────────────────────────────────────────────

    def add_subscription(
        self, telegram_id: str, room_no: str, target_serial: int, look_ahead: int
    ) -> int:
        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO subscriptions(telegram_id, room_no, target_serial, look_ahead, active, created_at)
                VALUES(?, ?, ?, ?, 1, ?)
                """,
                (telegram_id, room_no, target_serial, look_ahead, iso(utc_now())),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def remove_subscription(self, telegram_id: str, room_no: str) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE subscriptions SET active=0 WHERE telegram_id=? AND room_no=?",
                (telegram_id, room_no),
            )

    def list_active_subscriptions(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM subscriptions WHERE active=1"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_user_subscriptions(self, telegram_id: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM subscriptions WHERE telegram_id=? AND active=1",
                (telegram_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def was_notified_today(self, sub_id: int) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connect() as con:
            row = con.execute(
                "SELECT 1 FROM notification_log WHERE sub_id=? AND DATE(sent_at)=?",
                (sub_id, today),
            ).fetchone()
        return row is not None

    def log_notification(self, sub_id: int, payload: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO notification_log(sub_id, sent_at, payload) VALUES(?, ?, ?)",
                (sub_id, iso(utc_now()), payload),
            )

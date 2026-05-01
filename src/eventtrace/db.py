from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generator

log = logging.getLogger(__name__)


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

            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitor_state (
                  key   TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                """
            )

            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS causelist_bench (
                  id           INTEGER PRIMARY KEY AUTOINCREMENT,
                  list_date    TEXT NOT NULL,
                  court_no     TEXT NOT NULL,
                  bench_label  TEXT,
                  side         TEXT,
                  list_type    TEXT,
                  judges_json  TEXT NOT NULL DEFAULT '[]',
                  not_sitting  INTEGER NOT NULL DEFAULT 0,
                  vc_link      TEXT,
                  jurisdiction TEXT,
                  scraped_at   TEXT NOT NULL,
                  UNIQUE(list_date, court_no)
                );

                CREATE INDEX IF NOT EXISTS idx_causelist_bench_date
                  ON causelist_bench(list_date);
                CREATE INDEX IF NOT EXISTS idx_causelist_bench_court
                  ON causelist_bench(court_no, list_date);

                CREATE TABLE IF NOT EXISTS causelist_case (
                  id              INTEGER PRIMARY KEY AUTOINCREMENT,
                  bench_id        INTEGER NOT NULL REFERENCES causelist_bench(id) ON DELETE CASCADE,
                  list_date       TEXT NOT NULL,
                  court_no        TEXT NOT NULL,
                  serial_no       INTEGER NOT NULL,
                  case_ref        TEXT,
                  case_type       TEXT,
                  case_number     TEXT,
                  case_year       INTEGER,
                  petitioner      TEXT,
                  respondent      TEXT,
                  advocate        TEXT,
                  pro_se          INTEGER NOT NULL DEFAULT 0,
                  ia_numbers_json TEXT NOT NULL DEFAULT '[]',
                  section         TEXT,
                  subsection      TEXT,
                  hearing_type    TEXT,
                  raw_text        TEXT,
                  scraped_at      TEXT NOT NULL,
                  UNIQUE(bench_id, serial_no)
                );

                CREATE INDEX IF NOT EXISTS idx_causelist_case_ref
                  ON causelist_case(case_ref);
                CREATE INDEX IF NOT EXISTS idx_causelist_case_date_court
                  ON causelist_case(list_date, court_no);
                CREATE INDEX IF NOT EXISTS idx_causelist_case_type_year
                  ON causelist_case(case_type, case_year);
                CREATE INDEX IF NOT EXISTS idx_causelist_case_advocate
                  ON causelist_case(advocate);
                """
            )

            # Non-destructive column migrations — safe to re-run
            for _col_sql in [
                "ALTER TABLE subscriptions ADD COLUMN hearing_date TEXT",
                "ALTER TABLE subscriptions ADD COLUMN contact_type TEXT NOT NULL DEFAULT 'telegram'",
                "ALTER TABLE subscriptions ADD COLUMN last_notified_serial INTEGER",
                "ALTER TABLE subscriptions ADD COLUMN display_name TEXT",
                "ALTER TABLE subscriptions ADD COLUMN phone TEXT",
                "ALTER TABLE subscriptions ADD COLUMN alerted_at TEXT",
                "ALTER TABLE subscriptions ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0",
            ]:
                try:
                    con.execute(_col_sql)
                except sqlite3.OperationalError:
                    pass  # column already exists

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

    def list_vc_dates(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT DISTINCT date FROM vc_zoom_link ORDER BY date DESC"
            ).fetchall()
        return [r["date"] for r in rows]

    # ── Subscriptions ────────────────────────────────────────────────────────

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
        with self.connect() as con:
            cur = con.execute(
                """
                INSERT INTO subscriptions(
                  telegram_id, room_no, target_serial, look_ahead, active, created_at,
                  hearing_date, contact_type, display_name, phone
                )
                VALUES(?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id, room_no, target_serial, look_ahead, iso(utc_now()),
                    hearing_date, contact_type, display_name, phone,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def remove_subscription(self, telegram_id: str, room_no: str) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE subscriptions SET active=0 WHERE telegram_id=? AND room_no=?",
                (telegram_id, room_no),
            )

    def remove_whatsapp_subscription(self, phone: str, room_no: str) -> int:
        with self.connect() as con:
            cur = con.execute(
                "UPDATE subscriptions SET active=0 WHERE phone=? AND room_no=? AND contact_type='whatsapp' AND active=1",
                (phone, room_no),
            )
            return cur.rowcount

    def list_active_subscriptions(self, today: str | None = None) -> list[dict[str, Any]]:
        """Returns active subscriptions, optionally filtered to hearing_date = today.

        Rows with hearing_date IS NULL are always included (legacy / any-day).
        """
        with self.connect() as con:
            if today:
                rows = con.execute(
                    "SELECT * FROM subscriptions WHERE active=1"
                    " AND (hearing_date IS NULL OR hearing_date=?)",
                    (today,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM subscriptions WHERE active=1"
                ).fetchall()
        return [dict(r) for r in rows]

    def update_last_notified_serial(self, sub_id: int, serial: int) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE subscriptions SET last_notified_serial=? WHERE id=?",
                (serial, sub_id),
            )

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

    def mark_alerted(self, sub_id: int) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE subscriptions SET alerted_at=? WHERE id=?",
                (iso(utc_now()), sub_id),
            )

    def mark_reminder_sent(self, sub_id: int) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE subscriptions SET reminder_sent=1 WHERE id=?",
                (sub_id,),
            )

    def deactivate_subscription(self, sub_id: int) -> None:
        with self.connect() as con:
            con.execute("UPDATE subscriptions SET active=0 WHERE id=?", (sub_id,))

    def list_active_subscriptions_for_room(self, room_no: str, today: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM subscriptions WHERE active=1 AND room_no=?"
                " AND (hearing_date IS NULL OR hearing_date=?)",
                (room_no, today),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Monitor state ────────────────────────────────────────────────────────

    # ── Causelist ─────────────────────────────────────────────────────────────

    def get_causelist_bench(self, list_date: str, court_no: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM causelist_bench WHERE list_date=? AND court_no=?",
                (list_date, court_no),
            ).fetchone()
        return dict(row) if row else None

    def list_causelist_benches(self, list_date: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT cb.*, COUNT(cc.id) AS case_count
                FROM causelist_bench cb
                LEFT JOIN causelist_case cc ON cc.bench_id = cb.id
                WHERE cb.list_date=?
                GROUP BY cb.id
                ORDER BY cb.court_no
                """,
                (list_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_causelist_cases(self, list_date: str, court_no: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM causelist_case
                WHERE list_date=? AND court_no=?
                ORDER BY serial_no
                """,
                (list_date, court_no),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_causelist_case_by_serial(
        self, list_date: str, court_no: str, serial_no: int
    ) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT cc.*, cb.judges_json, cb.vc_link, cb.bench_label
                FROM causelist_case cc
                JOIN causelist_bench cb ON cb.id = cc.bench_id
                WHERE cc.list_date=? AND cc.court_no=? AND cc.serial_no=?
                """,
                (list_date, court_no, serial_no),
            ).fetchone()
        return dict(row) if row else None

    def search_causelist_cases(
        self,
        case_ref: str | None = None,
        advocate: str | None = None,
        party: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if case_ref:
            if "/" in case_ref:
                clauses.append("cc.case_ref = ?")
                params.append(case_ref)
            else:
                clauses.append("cc.case_ref LIKE ?")
                params.append(f"%{case_ref}%")
        if advocate:
            clauses.append("cc.advocate LIKE ?")
            params.append(f"%{advocate.upper()}%")
        if party:
            p = party.upper()
            clauses.append("(cc.petitioner LIKE ? OR cc.respondent LIKE ?)")
            params += [f"%{p}%", f"%{p}%"]
        if date_from:
            clauses.append("cc.list_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("cc.list_date <= ?")
            params.append(date_to)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        with self.connect() as con:
            rows = con.execute(
                f"""
                SELECT cc.*, cb.judges_json, cb.vc_link
                FROM causelist_case cc
                JOIN causelist_bench cb ON cb.id = cc.bench_id
                {where}
                ORDER BY cc.list_date DESC, cc.court_no, cc.serial_no
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def list_causelist_dates(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT DISTINCT list_date FROM causelist_bench ORDER BY list_date DESC"
            ).fetchall()
        return [r["list_date"] for r in rows]

    # ── Monitor state ────────────────────────────────────────────────────────

    def set_monitor_state(self, key: str, value: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO monitor_state(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_monitor_state(self, key: str) -> str | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT value FROM monitor_state WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    # ── Causelist bulk upsert ────────────────────────────────────────────────

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        """Upsert parsed causelist blocks. Returns number of cases stored."""
        now_iso = iso(scraped_at or utc_now())
        total = 0
        with self.connect() as con:
            for court in parsed:
                bench = court["bench"]
                cases = court["cases"]
                if not bench.get("court_no") or not bench.get("list_date"):
                    continue
                judges_json = json.dumps(bench.get("judges") or [], ensure_ascii=False)
                not_sitting = 1 if bench.get("not_sitting") else 0
                con.execute(
                    """
                    INSERT INTO causelist_bench(
                      list_date, court_no, bench_label, side, list_type,
                      judges_json, not_sitting, vc_link, jurisdiction, scraped_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(list_date, court_no) DO UPDATE SET
                      bench_label=excluded.bench_label, side=excluded.side,
                      list_type=excluded.list_type, judges_json=excluded.judges_json,
                      not_sitting=excluded.not_sitting, vc_link=excluded.vc_link,
                      jurisdiction=excluded.jurisdiction, scraped_at=excluded.scraped_at
                    """,
                    (
                        bench["list_date"], bench["court_no"],
                        bench.get("bench_label"), bench.get("side"), bench.get("list_type"),
                        judges_json, not_sitting, bench.get("vc_link"),
                        bench.get("jurisdiction_notes"), now_iso,
                    ),
                )
                row = con.execute(
                    "SELECT id FROM causelist_bench WHERE list_date=? AND court_no=?",
                    (bench["list_date"], bench["court_no"]),
                ).fetchone()
                bench_id = row["id"]
                for case in cases:
                    ia_json = json.dumps(case.get("ia_numbers") or [], ensure_ascii=False)
                    con.execute(
                        """
                        INSERT INTO causelist_case(
                          bench_id, list_date, court_no, serial_no,
                          case_ref, case_type, case_number, case_year,
                          petitioner, respondent, advocate, pro_se,
                          ia_numbers_json, section, subsection, hearing_type,
                          raw_text, scraped_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(bench_id, serial_no) DO UPDATE SET
                          case_ref=excluded.case_ref, case_type=excluded.case_type,
                          case_number=excluded.case_number, case_year=excluded.case_year,
                          petitioner=excluded.petitioner, respondent=excluded.respondent,
                          advocate=excluded.advocate, pro_se=excluded.pro_se,
                          ia_numbers_json=excluded.ia_numbers_json,
                          section=excluded.section, subsection=excluded.subsection,
                          hearing_type=excluded.hearing_type, raw_text=excluded.raw_text,
                          scraped_at=excluded.scraped_at
                        """,
                        (
                            bench_id, bench["list_date"], bench["court_no"], case["serial_no"],
                            case["case_ref"], case["case_type"], case["case_number"], case["case_year"],
                            case.get("petitioner"), case.get("respondent"), case.get("advocate"),
                            1 if case.get("pro_se") else 0,
                            ia_json, case.get("section"), case.get("subsection"),
                            case.get("hearing_type"), case.get("raw_text"), now_iso,
                        ),
                    )
                    total += 1
        return total


# ── PostgreSQL backend ────────────────────────────────────────────────────────

class PostgresDB:
    """PostgreSQL-backed store with the same public interface as DB."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None  # lazy — created on first use

    def _get_pool(self):
        if self._pool is None:
            import psycopg2  # type: ignore[import]
            import psycopg2.pool  # type: ignore[import]
            for attempt in range(10):
                try:
                    self._pool = psycopg2.pool.ThreadedConnectionPool(1, 5, self._dsn)
                    return self._pool
                except psycopg2.OperationalError as exc:
                    if attempt == 9:
                        raise
                    log.warning("Postgres not ready (attempt %d/10): %s — retrying in 3s", attempt + 1, exc)
                    time.sleep(3)
        return self._pool

    @contextmanager
    def _cursor(self) -> Generator:
        import psycopg2.extras  # type: ignore[import]
        pool = self._get_pool()
        con = pool.getconn()
        try:
            cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            cur.close()
            pool.putconn(con)

    def ensure_schema(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS current_state (
              court_id TEXT PRIMARY KEY,
              data_json TEXT NOT NULL,
              last_seen_time TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS field_state (
              court_id TEXT NOT NULL,
              field_name TEXT NOT NULL,
              value TEXT,
              start_time TEXT NOT NULL,
              last_seen_time TEXT NOT NULL,
              PRIMARY KEY (court_id, field_name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS event_trace (
              id SERIAL PRIMARY KEY,
              court_id TEXT NOT NULL,
              field_name TEXT NOT NULL,
              old_value TEXT,
              new_value TEXT,
              start_time TEXT NOT NULL,
              end_time TEXT NOT NULL,
              duration_seconds INTEGER NOT NULL,
              observed_time TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_event_trace_time ON event_trace(observed_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_event_trace_court ON event_trace(court_id, observed_time DESC)",
            """
            CREATE TABLE IF NOT EXISTS vc_zoom_link (
              date       TEXT NOT NULL,
              room_no    TEXT NOT NULL,
              zoom_url   TEXT NOT NULL,
              scraped_at TEXT NOT NULL,
              PRIMARY KEY (date, room_no)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
              id            SERIAL PRIMARY KEY,
              telegram_id   TEXT NOT NULL,
              room_no       TEXT NOT NULL,
              target_serial INTEGER NOT NULL,
              look_ahead    INTEGER NOT NULL DEFAULT 5,
              active        INTEGER NOT NULL DEFAULT 1,
              created_at    TEXT NOT NULL,
              hearing_date  TEXT,
              contact_type  TEXT NOT NULL DEFAULT 'telegram',
              last_notified_serial INTEGER,
              display_name  TEXT,
              phone         TEXT,
              alerted_at    TEXT,
              reminder_sent INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notification_log (
              id     SERIAL PRIMARY KEY,
              sub_id INTEGER REFERENCES subscriptions(id),
              sent_at TEXT NOT NULL,
              payload TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor_state (
              key   TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS causelist_bench (
              id           SERIAL PRIMARY KEY,
              list_date    TEXT NOT NULL,
              court_no     TEXT NOT NULL,
              bench_label  TEXT,
              side         TEXT,
              list_type    TEXT,
              judges_json  TEXT NOT NULL DEFAULT '[]',
              not_sitting  INTEGER NOT NULL DEFAULT 0,
              vc_link      TEXT,
              jurisdiction TEXT,
              scraped_at   TEXT NOT NULL,
              UNIQUE(list_date, court_no)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_causelist_bench_date ON causelist_bench(list_date)",
            "CREATE INDEX IF NOT EXISTS idx_causelist_bench_court ON causelist_bench(court_no, list_date)",
            """
            CREATE TABLE IF NOT EXISTS causelist_case (
              id              SERIAL PRIMARY KEY,
              bench_id        INTEGER NOT NULL REFERENCES causelist_bench(id) ON DELETE CASCADE,
              list_date       TEXT NOT NULL,
              court_no        TEXT NOT NULL,
              serial_no       INTEGER NOT NULL,
              case_ref        TEXT,
              case_type       TEXT,
              case_number     TEXT,
              case_year       INTEGER,
              petitioner      TEXT,
              respondent      TEXT,
              advocate        TEXT,
              pro_se          INTEGER NOT NULL DEFAULT 0,
              ia_numbers_json TEXT NOT NULL DEFAULT '[]',
              section         TEXT,
              subsection      TEXT,
              hearing_type    TEXT,
              raw_text        TEXT,
              scraped_at      TEXT NOT NULL,
              UNIQUE(bench_id, serial_no)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_causelist_case_ref ON causelist_case(case_ref)",
            "CREATE INDEX IF NOT EXISTS idx_causelist_case_date_court ON causelist_case(list_date, court_no)",
            "CREATE INDEX IF NOT EXISTS idx_causelist_case_type_year ON causelist_case(case_type, case_year)",
            "CREATE INDEX IF NOT EXISTS idx_causelist_case_advocate ON causelist_case(advocate)",
        ]
        with self._cursor() as cur:
            # Try to enable trigram extension — non-fatal if superuser not available
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            except Exception:
                pass
            for stmt in ddl:
                cur.execute(stmt)
            # Trigram indexes — non-fatal if extension unavailable
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_cc_advocate_trgm ON causelist_case USING GIN (advocate gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS idx_cc_petitioner_trgm ON causelist_case USING GIN (petitioner gin_trgm_ops)",
                "CREATE INDEX IF NOT EXISTS idx_cc_respondent_trgm ON causelist_case USING GIN (respondent gin_trgm_ops)",
            ]:
                try:
                    cur.execute(idx_sql)
                except Exception:
                    pass

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
            cur.execute("SELECT court_id, data_json, last_seen_time FROM current_state ORDER BY court_id ASC")
            rows = cur.fetchall()
        return [{"court_id": r["court_id"], "data": json.loads(r["data_json"]), "last_seen_time": r["last_seen_time"]} for r in rows]

    def list_event_traces(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
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
            cur.execute("SELECT court_id FROM field_state WHERE field_name='__present__' AND value='0'")
            return [r["court_id"] for r in cur.fetchall()]

    def list_serial_start_times(self) -> dict[str, str]:
        with self._cursor() as cur:
            cur.execute("SELECT court_id, start_time FROM field_state WHERE field_name='cause_list_sr_no'")
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

    # ── VC Zoom Links ────────────────────────────────────────────────────────

    def upsert_vc_zoom_link(self, date: str, room_no: str, zoom_url: str, scraped_at: datetime) -> None:
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

    # ── Subscriptions ────────────────────────────────────────────────────────

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
                (telegram_id, room_no, target_serial, look_ahead, iso(utc_now()),
                 hearing_date, contact_type, display_name, phone),
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
            cur.execute("UPDATE subscriptions SET alerted_at=%s WHERE id=%s", (iso(utc_now()), sub_id))

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

    # ── Monitor state ────────────────────────────────────────────────────────

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

    # ── Causelist ────────────────────────────────────────────────────────────

    def get_causelist_bench(self, list_date: str, court_no: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM causelist_bench WHERE list_date=%s AND court_no=%s",
                (list_date, court_no),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def list_causelist_benches(self, list_date: str) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT cb.*, COUNT(cc.id) AS case_count
                FROM causelist_bench cb
                LEFT JOIN causelist_case cc ON cc.bench_id = cb.id
                WHERE cb.list_date=%s
                GROUP BY cb.id
                ORDER BY cb.court_no
                """,
                (list_date,),
            )
            return [dict(r) for r in cur.fetchall()]

    def list_causelist_cases(self, list_date: str, court_no: str) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM causelist_case WHERE list_date=%s AND court_no=%s ORDER BY serial_no",
                (list_date, court_no),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_causelist_case_by_serial(
        self, list_date: str, court_no: str, serial_no: int
    ) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT cc.*, cb.judges_json, cb.vc_link, cb.bench_label
                FROM causelist_case cc
                JOIN causelist_bench cb ON cb.id = cc.bench_id
                WHERE cc.list_date=%s AND cc.court_no=%s AND cc.serial_no=%s
                """,
                (list_date, court_no, serial_no),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def search_causelist_cases(
        self,
        case_ref: str | None = None,
        advocate: str | None = None,
        party: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if case_ref:
            if "/" in case_ref:
                clauses.append("cc.case_ref = %s")
                params.append(case_ref)
            else:
                clauses.append("cc.case_ref ILIKE %s")
                params.append(f"%{case_ref}%")
        if advocate:
            clauses.append("cc.advocate ILIKE %s")
            params.append(f"%{advocate}%")
        if party:
            clauses.append("(cc.petitioner ILIKE %s OR cc.respondent ILIKE %s)")
            params += [f"%{party}%", f"%{party}%"]
        if date_from:
            clauses.append("cc.list_date >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("cc.list_date <= %s")
            params.append(date_to)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT cc.*, cb.judges_json, cb.vc_link
                FROM causelist_case cc
                JOIN causelist_bench cb ON cb.id = cc.bench_id
                {where}
                ORDER BY cc.list_date DESC, cc.court_no, cc.serial_no
                LIMIT %s
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def list_causelist_dates(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute("SELECT DISTINCT list_date FROM causelist_bench ORDER BY list_date DESC")
            return [r["list_date"] for r in cur.fetchall()]

    # ── Causelist bulk upsert ────────────────────────────────────────────────

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        now_iso = iso(scraped_at or utc_now())
        total = 0
        with self._cursor() as cur:
            for court in parsed:
                bench = court["bench"]
                cases = court["cases"]
                if not bench.get("court_no") or not bench.get("list_date"):
                    continue
                judges_json = json.dumps(bench.get("judges") or [], ensure_ascii=False)
                not_sitting = 1 if bench.get("not_sitting") else 0
                cur.execute(
                    """
                    INSERT INTO causelist_bench(
                      list_date, court_no, bench_label, side, list_type,
                      judges_json, not_sitting, vc_link, jurisdiction, scraped_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(list_date, court_no) DO UPDATE SET
                      bench_label=EXCLUDED.bench_label, side=EXCLUDED.side,
                      list_type=EXCLUDED.list_type, judges_json=EXCLUDED.judges_json,
                      not_sitting=EXCLUDED.not_sitting, vc_link=EXCLUDED.vc_link,
                      jurisdiction=EXCLUDED.jurisdiction, scraped_at=EXCLUDED.scraped_at
                    RETURNING id
                    """,
                    (
                        bench["list_date"], bench["court_no"],
                        bench.get("bench_label"), bench.get("side"), bench.get("list_type"),
                        judges_json, not_sitting, bench.get("vc_link"),
                        bench.get("jurisdiction_notes"), now_iso,
                    ),
                )
                bench_id = cur.fetchone()["id"]
                for case in cases:
                    ia_json = json.dumps(case.get("ia_numbers") or [], ensure_ascii=False)
                    cur.execute(
                        """
                        INSERT INTO causelist_case(
                          bench_id, list_date, court_no, serial_no,
                          case_ref, case_type, case_number, case_year,
                          petitioner, respondent, advocate, pro_se,
                          ia_numbers_json, section, subsection, hearing_type,
                          raw_text, scraped_at
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(bench_id, serial_no) DO UPDATE SET
                          case_ref=EXCLUDED.case_ref, case_type=EXCLUDED.case_type,
                          case_number=EXCLUDED.case_number, case_year=EXCLUDED.case_year,
                          petitioner=EXCLUDED.petitioner, respondent=EXCLUDED.respondent,
                          advocate=EXCLUDED.advocate, pro_se=EXCLUDED.pro_se,
                          ia_numbers_json=EXCLUDED.ia_numbers_json,
                          section=EXCLUDED.section, subsection=EXCLUDED.subsection,
                          hearing_type=EXCLUDED.hearing_type, raw_text=EXCLUDED.raw_text,
                          scraped_at=EXCLUDED.scraped_at
                        """,
                        (
                            bench_id, bench["list_date"], bench["court_no"], case["serial_no"],
                            case["case_ref"], case["case_type"], case["case_number"], case["case_year"],
                            case.get("petitioner"), case.get("respondent"), case.get("advocate"),
                            1 if case.get("pro_se") else 0,
                            ia_json, case.get("section"), case.get("subsection"),
                            case.get("hearing_type"), case.get("raw_text"), now_iso,
                        ),
                    )
                    total += 1
        return total


# ── Factory ───────────────────────────────────────────────────────────────────

def get_db(settings: Any) -> "DB | PostgresDB":
    """Return DB or PostgresDB based on DATABASE_URL env var."""
    dsn = getattr(settings, "database_url", None)
    if dsn:
        return PostgresDB(dsn)
    return DB(settings.db_path)

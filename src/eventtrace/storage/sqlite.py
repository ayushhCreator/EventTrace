from __future__ import annotations

import structlog
import sqlite3
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine

from ..domain.models import EventTrace
from .repositories.auth_alchemy import SQLAlchemyAuthRepository
from .repositories.causelist_alchemy import SQLAlchemyCauselistRepository
from .repositories.events_alchemy import SQLAlchemyEventsRepository
from .repositories.subscriptions_alchemy import SQLAlchemySubscriptionsRepository
from .repositories.timeline_alchemy import SQLAlchemyTimelineRepository

log = structlog.get_logger()


def _default_prefs() -> dict:
    return {
        "whatsapp": True,
        "email": True,
        "serial_alerts": True,
        "causelist_alerts": True,
        "change_alerts": True,
    }


class DB:
    def __init__(self, path: str) -> None:
        self.path = path
        self._engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        self._events = SQLAlchemyEventsRepository(self._engine)
        self._subscriptions = SQLAlchemySubscriptionsRepository(self._engine)
        self._causelist = SQLAlchemyCauselistRepository(self._engine)
        self._auth = SQLAlchemyAuthRepository(self._engine)
        self._timeline = SQLAlchemyTimelineRepository(self._engine)

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
                for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
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
                  last_seen_time TEXT NOT NULL,
                  source_court TEXT NOT NULL DEFAULT 'CHD'
                );

                CREATE TABLE IF NOT EXISTS field_state (
                  court_id TEXT NOT NULL,
                  field_name TEXT NOT NULL,
                  value TEXT,
                  start_time TEXT NOT NULL,
                  last_seen_time TEXT NOT NULL,
                  source_court TEXT NOT NULL DEFAULT 'CHD',
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
                  observed_time TEXT NOT NULL,
                  source_court TEXT NOT NULL DEFAULT 'CHD'
                );

                CREATE INDEX IF NOT EXISTS idx_event_trace_time
                  ON event_trace(observed_time DESC);
                CREATE INDEX IF NOT EXISTS idx_event_trace_court
                  ON event_trace(court_id, observed_time DESC);
                CREATE INDEX IF NOT EXISTS idx_event_trace_source_court
                  ON event_trace(source_court, court_id, observed_time DESC);
                CREATE INDEX IF NOT EXISTS idx_current_state_source_court
                  ON current_state(source_court, court_id);
                CREATE INDEX IF NOT EXISTS idx_field_state_source_court
                  ON field_state(source_court, court_id, field_name);

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
                  source_court TEXT NOT NULL DEFAULT 'CHD',
                  UNIQUE(list_date, court_no)
                );

                CREATE INDEX IF NOT EXISTS idx_causelist_bench_date
                  ON causelist_bench(list_date);
                CREATE INDEX IF NOT EXISTS idx_causelist_bench_court
                  ON causelist_bench(court_no, list_date);
                CREATE INDEX IF NOT EXISTS idx_causelist_bench_source_court
                  ON causelist_bench(source_court, list_date, court_no);

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

            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id         TEXT PRIMARY KEY,
                  phone      TEXT NOT NULL UNIQUE,
                  email      TEXT,
                  name       TEXT,
                  role       TEXT NOT NULL DEFAULT 'client',
                  tier       TEXT NOT NULL DEFAULT 'free',
                  verified   INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phone_otps (
                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                  phone      TEXT NOT NULL,
                  otp_hash   TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  attempts   INTEGER NOT NULL DEFAULT 0,
                  used       INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_otps (
                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                  email      TEXT NOT NULL,
                  user_id    TEXT NOT NULL,
                  otp_hash   TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  attempts   INTEGER NOT NULL DEFAULT 0,
                  used       INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL
                );
                """
            )

            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracked_cases (
                  id           INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  case_ref     TEXT NOT NULL,
                  court_no     TEXT,
                  bench_label  TEXT,
                  judges_json  TEXT,
                  list_date    TEXT,
                  serial_no    INTEGER,
                  petitioner   TEXT,
                  respondent   TEXT,
                  alert_active INTEGER NOT NULL DEFAULT 0,
                  alert_serial INTEGER,
                  look_ahead   INTEGER NOT NULL DEFAULT 5,
                  added_at     TEXT NOT NULL,
                  UNIQUE(user_id, case_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_tracked_cases_user ON tracked_cases(user_id);
                CREATE INDEX IF NOT EXISTS idx_tracked_cases_ref ON tracked_cases(case_ref);
                """
            )

            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS case_snapshots (
                  id         INTEGER PRIMARY KEY AUTOINCREMENT,
                  case_ref   TEXT NOT NULL,
                  list_date  TEXT NOT NULL,
                  data_json  TEXT NOT NULL,
                  hash       TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(case_ref, list_date)
                );
                CREATE INDEX IF NOT EXISTS idx_case_snapshots_ref
                  ON case_snapshots(case_ref);
                CREATE INDEX IF NOT EXISTS idx_case_snapshots_date
                  ON case_snapshots(list_date);

                CREATE TABLE IF NOT EXISTS case_timeline_events (
                  id             INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  case_ref       TEXT NOT NULL,
                  event_type     TEXT NOT NULL,
                  event_date     TEXT NOT NULL,
                  change_summary TEXT,
                  created_at     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cte_user_ref
                  ON case_timeline_events(user_id, case_ref);
                CREATE INDEX IF NOT EXISTS idx_cte_event_date
                  ON case_timeline_events(event_date);
                """
            )

            # Non-destructive column migrations — safe to re-run
            for _col_sql in [
                # causelist_bench: source tracking + location/time fields
                "ALTER TABLE causelist_bench ADD COLUMN source_id TEXT",
                "ALTER TABLE causelist_bench ADD COLUMN at_time TEXT",
                "ALTER TABLE causelist_bench ADD COLUMN floor TEXT",
                "ALTER TABLE causelist_bench ADD COLUMN building TEXT",
                "ALTER TABLE causelist_bench ADD COLUMN source_court TEXT NOT NULL DEFAULT 'CHD'",
                # multi-court support columns
                "ALTER TABLE current_state ADD COLUMN source_court TEXT NOT NULL DEFAULT 'CHD'",
                "ALTER TABLE field_state ADD COLUMN source_court TEXT NOT NULL DEFAULT 'CHD'",
                "ALTER TABLE event_trace ADD COLUMN source_court TEXT NOT NULL DEFAULT 'CHD'",
                # subscriptions
                "ALTER TABLE subscriptions ADD COLUMN hearing_date TEXT",
                "ALTER TABLE subscriptions ADD COLUMN contact_type TEXT NOT NULL DEFAULT 'telegram'",
                "ALTER TABLE subscriptions ADD COLUMN last_notified_serial INTEGER",
                "ALTER TABLE subscriptions ADD COLUMN display_name TEXT",
                "ALTER TABLE subscriptions ADD COLUMN phone TEXT",
                "ALTER TABLE subscriptions ADD COLUMN alerted_at TEXT",
                "ALTER TABLE subscriptions ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0",
                # tracked_cases: serial-alert deduplication
                "ALTER TABLE tracked_cases ADD COLUMN alerted_at TEXT",
                # users: notification preferences + email verification
                "ALTER TABLE users ADD COLUMN notification_prefs TEXT",
                "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0",
                # notification_log: enrich for tracked-case alerts
                "ALTER TABLE notification_log ADD COLUMN tracked_case_id INTEGER",
                "ALTER TABLE notification_log ADD COLUMN status TEXT NOT NULL DEFAULT 'sent'",
            ]:
                try:
                    con.execute(_col_sql)
                except sqlite3.OperationalError:
                    pass  # column already exists

            # Backfill NULLs so existing rows have canonical side/list_type/source_id.
            con.execute("""
                UPDATE causelist_bench
                SET side      = 'APPELLATE SIDE',
                    list_type = 'DAILY',
                    source_id = 'appellate_static'
                WHERE side IS NULL OR list_type IS NULL
            """)

            # SQLite can't ALTER a UNIQUE constraint — migrate to new schema via
            # table rename if the old 2-col constraint is still in place.
            old_schema = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='causelist_bench'"
            ).fetchone()
            # Match only the old 2-column constraint — not the new 4-column one which
            # also starts with "UNIQUE(list_date, court_no".
            needs_migration = (
                old_schema is not None
                and "UNIQUE(list_date, court_no)" in (old_schema["sql"] or "")
                and "UNIQUE(list_date, court_no, side" not in (old_schema["sql"] or "")
            )
            # Detect if a previous migration (without legacy_alter_table) left
            # causelist_case.bench_id FK pointing at causelist_bench_old instead
            # of causelist_bench. If so, rebuild causelist_case with the correct FK.
            case_schema_row = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='causelist_case'"
            ).fetchone()
            case_sql = (case_schema_row["sql"] or "") if case_schema_row else ""
            if "causelist_bench_old" in case_sql:
                # The FK was silently rewritten — rebuild causelist_case with correct FK
                con.executescript("""
                    PRAGMA legacy_alter_table = ON;
                    ALTER TABLE causelist_case RENAME TO causelist_case_old;
                    PRAGMA legacy_alter_table = OFF;

                    CREATE TABLE causelist_case (
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

                    INSERT OR IGNORE INTO causelist_case
                      SELECT * FROM causelist_case_old;

                    DROP TABLE causelist_case_old;

                    CREATE INDEX IF NOT EXISTS idx_causelist_case_ref
                      ON causelist_case(case_ref);
                    CREATE INDEX IF NOT EXISTS idx_causelist_case_date_court
                      ON causelist_case(list_date, court_no);
                    CREATE INDEX IF NOT EXISTS idx_causelist_case_type_year
                      ON causelist_case(case_type, case_year);
                    CREATE INDEX IF NOT EXISTS idx_causelist_case_advocate
                      ON causelist_case(advocate);
                """)

            # Recover from a previously aborted migration that left the old table around.
            orphan = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='causelist_bench_old'"
            ).fetchone()
            if orphan and old_schema is None:
                # causelist_bench was renamed but new one never created — recreate + copy
                con.executescript("""
                    PRAGMA legacy_alter_table = ON;
                    CREATE TABLE IF NOT EXISTS causelist_bench (
                      id           INTEGER PRIMARY KEY AUTOINCREMENT,
                      list_date    TEXT NOT NULL,
                      court_no     TEXT NOT NULL,
                      bench_label  TEXT,
                      side         TEXT NOT NULL DEFAULT 'APPELLATE SIDE',
                      list_type    TEXT NOT NULL DEFAULT 'DAILY',
                      judges_json  TEXT NOT NULL DEFAULT '[]',
                      not_sitting  INTEGER NOT NULL DEFAULT 0,
                      vc_link      TEXT,
                      jurisdiction TEXT,
                      scraped_at   TEXT NOT NULL,
                      source_id    TEXT,
                      at_time      TEXT,
                      floor        TEXT,
                      building     TEXT,
                      source_court TEXT NOT NULL DEFAULT 'CHD',
                      UNIQUE(list_date, court_no, side, list_type)
                    );
                    INSERT OR IGNORE INTO causelist_bench
                      SELECT id, list_date, court_no, bench_label,
                             COALESCE(side, 'APPELLATE SIDE'),
                             COALESCE(list_type, 'DAILY'),
                             judges_json, not_sitting, vc_link, jurisdiction, scraped_at,
                             source_id,
                             at_time, floor, building,
                             COALESCE(source_court, 'CHD')
                      FROM causelist_bench_old;
                    DROP TABLE causelist_bench_old;
                    PRAGMA legacy_alter_table = OFF;
                """)

            if needs_migration:
                # PRAGMA legacy_alter_table prevents SQLite 3.26+ from rewriting
                # FK references in causelist_case when we rename causelist_bench.
                # Without it, caselist_case.bench_id FK silently re-points to
                # causelist_bench_old, making UPSERTs fail after the DROP.
                con.executescript("""
                    PRAGMA legacy_alter_table = ON;

                    ALTER TABLE causelist_bench RENAME TO causelist_bench_old;

                    CREATE TABLE causelist_bench (
                      id           INTEGER PRIMARY KEY AUTOINCREMENT,
                      list_date    TEXT NOT NULL,
                      court_no     TEXT NOT NULL,
                      bench_label  TEXT,
                      side         TEXT NOT NULL DEFAULT 'APPELLATE SIDE',
                      list_type    TEXT NOT NULL DEFAULT 'DAILY',
                      judges_json  TEXT NOT NULL DEFAULT '[]',
                      not_sitting  INTEGER NOT NULL DEFAULT 0,
                      vc_link      TEXT,
                      jurisdiction TEXT,
                      scraped_at   TEXT NOT NULL,
                      source_id    TEXT,
                      at_time      TEXT,
                      floor        TEXT,
                      building     TEXT,
                      source_court TEXT NOT NULL DEFAULT 'CHD',
                      UNIQUE(list_date, court_no, side, list_type)
                    );

                    INSERT INTO causelist_bench
                      SELECT id, list_date, court_no, bench_label,
                             COALESCE(side, 'APPELLATE SIDE'),
                             COALESCE(list_type, 'DAILY'),
                             judges_json, not_sitting, vc_link, jurisdiction, scraped_at,
                             source_id,
                             at_time, floor, building,
                             COALESCE(source_court, 'CHD')
                      FROM causelist_bench_old;

                    DROP TABLE causelist_bench_old;

                    PRAGMA legacy_alter_table = OFF;

                    CREATE INDEX IF NOT EXISTS idx_causelist_bench_date
                      ON causelist_bench(list_date);
                    CREATE INDEX IF NOT EXISTS idx_causelist_bench_court
                      ON causelist_bench(court_no, list_date);
                    CREATE INDEX IF NOT EXISTS idx_causelist_bench_source_court
                      ON causelist_bench(source_court, list_date, court_no);
                """)

    # ── Events delegation ────────────────────────────────────────────────────

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        return self._events.upsert_current_state(court_id, row, seen_time)

    def get_field_state(self, court_id: str, field_name: str):
        return self._events.get_field_state(court_id, field_name)

    def upsert_field_state(
        self,
        court_id: str,
        field_name: str,
        value: str | None,
        start_time: datetime,
        last_seen_time: datetime,
    ) -> None:
        return self._events.upsert_field_state(
            court_id, field_name, value, start_time, last_seen_time
        )

    def touch_field_state(self, court_id: str, field_name: str, last_seen_time: datetime) -> None:
        return self._events.touch_field_state(court_id, field_name, last_seen_time)

    def insert_event_trace(self, trace: EventTrace, observed_time: datetime) -> None:
        return self._events.insert_event_trace(trace, observed_time)

    def insert_change(self, change: EventTrace, observed_time: datetime) -> None:
        return self._events.insert_change(change, observed_time)

    def list_current_state(self) -> list[dict[str, Any]]:
        return self._events.list_current_state()

    def list_event_traces(
        self, limit: int = 200, court_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self._events.list_event_traces(limit=limit, court_id=court_id)

    def list_changes(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
        return self._events.list_changes(limit=limit, court_id=court_id)

    def list_field_state(self, court_id: str) -> list[dict[str, Any]]:
        return self._events.list_field_state(court_id)

    def list_field_names(self, court_id: str) -> set[str]:
        return self._events.list_field_names(court_id)

    def list_absent_court_ids(self) -> list[str]:
        return self._events.list_absent_court_ids()

    def list_serial_start_times(self) -> dict[str, str]:
        return self._events.list_serial_start_times()

    def known_courts(self) -> set[str]:
        return self._events.known_courts()

    def list_active_dates(self) -> list[str]:
        return self._events.list_active_dates()

    def list_day_activity(self, date_str: str) -> list[dict[str, Any]]:
        return self._events.list_day_activity(date_str)

    def set_monitor_state(self, key: str, value: str) -> None:
        return self._events.set_monitor_state(key, value)

    def get_monitor_state(self, key: str) -> str | None:
        return self._events.get_monitor_state(key)

    def upsert_vc_zoom_link(
        self, date: str, room_no: str, zoom_url: str, scraped_at: datetime
    ) -> None:
        return self._events.upsert_vc_zoom_link(date, room_no, zoom_url, scraped_at)

    def get_vc_zoom_links(self, date: str) -> dict[str, str]:
        return self._events.get_vc_zoom_links(date)

    def list_vc_dates(self) -> list[str]:
        return self._events.list_vc_dates()

    # ── Subscriptions delegation ─────────────────────────────────────────────

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
        return self._subscriptions.add_subscription(
            telegram_id,
            room_no,
            target_serial,
            look_ahead,
            hearing_date,
            contact_type,
            display_name,
            phone,
        )

    def remove_subscription(self, telegram_id: str, room_no: str) -> None:
        return self._subscriptions.remove_subscription(telegram_id, room_no)

    def remove_whatsapp_subscription(self, phone: str, room_no: str) -> int:
        return self._subscriptions.remove_whatsapp_subscription(phone, room_no)

    def list_active_subscriptions(self, today: str | None = None) -> list[dict[str, Any]]:
        return self._subscriptions.list_active_subscriptions(today)

    def update_last_notified_serial(self, sub_id: int, serial: int) -> None:
        return self._subscriptions.update_last_notified_serial(sub_id, serial)

    def list_user_subscriptions(self, telegram_id: str) -> list[dict[str, Any]]:
        return self._subscriptions.list_user_subscriptions(telegram_id)

    def was_notified_today(self, sub_id: int) -> bool:
        return self._subscriptions.was_notified_today(sub_id)

    def log_notification(self, sub_id: int, payload: str) -> None:
        return self._subscriptions.log_notification(sub_id, payload)

    def mark_alerted(self, sub_id: int) -> None:
        return self._subscriptions.mark_alerted(sub_id)

    def mark_reminder_sent(self, sub_id: int) -> None:
        return self._subscriptions.mark_reminder_sent(sub_id)

    def deactivate_subscription(self, sub_id: int) -> None:
        return self._subscriptions.deactivate_subscription(sub_id)

    def list_active_subscriptions_for_room(self, room_no: str, today: str) -> list[dict]:
        return self._subscriptions.list_active_subscriptions_for_room(room_no, today)

    # ── Causelist delegation ─────────────────────────────────────────────────

    def get_causelist_bench(
        self, list_date: str, court_no: str, side: str | None = None, list_type: str | None = None, source_id: str | None = None
    ) -> dict[str, Any] | None:
        return self._causelist.get_causelist_bench(
            list_date, court_no, side=side, list_type=list_type, source_id=source_id
        )

    def list_causelist_benches(
        self, list_date: str, side: str | None = None, list_type: str | None = None, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self._causelist.list_causelist_benches(list_date, side=side, list_type=list_type, source_id=source_id)

    def list_causelist_cases(
        self, list_date: str, court_no: str, side: str | None = None, list_type: str | None = None, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self._causelist.list_causelist_cases(
            list_date, court_no, side=side, list_type=list_type, source_id=source_id
        )

    def get_causelist_case_by_serial(
        self, list_date: str, court_no: str, serial_no: int
    ) -> dict[str, Any] | None:
        return self._causelist.get_causelist_case_by_serial(list_date, court_no, serial_no)

    def search_causelist_cases(
        self,
        case_ref: str | None = None,
        advocate: str | None = None,
        party: str | None = None,
        judge: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        side: str | None = None,
        list_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._causelist.search_causelist_cases(
            case_ref,
            advocate,
            party,
            judge,
            date_from,
            date_to,
            side=side,
            list_type=list_type,
            limit=limit,
        )

    def list_causelist_dates(self) -> list[str]:
        return self._causelist.list_causelist_dates()

    def is_causelist_source_scraped(self, list_date: str, source_id: str) -> bool:
        return self._causelist.is_causelist_source_scraped(list_date, source_id)

    def list_causelist_prefixes(self) -> list[str]:
        return self._causelist.list_causelist_prefixes()

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        return self._causelist.store_causelist(parsed, scraped_at)

    # ── Auth delegation ──────────────────────────────────────────────────────

    def get_user_by_phone(self, phone: str) -> dict | None:
        return self._auth.get_user_by_phone(phone)

    def get_user_by_id(self, user_id: str) -> dict | None:
        return self._auth.get_user_by_id(user_id)

    def upsert_user(self, phone: str, name: str | None = None, email: str | None = None) -> dict:
        return self._auth.upsert_user(phone, name, email)

    def mark_user_verified(self, phone: str) -> None:
        return self._auth.mark_user_verified(phone)

    def save_otp(self, phone: str, otp_hash: str, expires_at: Any) -> None:
        return self._auth.save_otp(phone, otp_hash, expires_at)

    def get_latest_otp(self, phone: str) -> dict | None:
        return self._auth.get_latest_otp(phone)

    def increment_otp_attempts(self, otp_id: int) -> None:
        return self._auth.increment_otp_attempts(otp_id)

    def mark_otp_used(self, otp_id: int) -> None:
        return self._auth.mark_otp_used(otp_id)

    def update_user_profile(self, user_id: str, name: str | None, email: str | None, role: str | None = None, bar_enrollment_number: str | None = None, firm_name: str | None = None, secondary_email: str | None = None) -> dict | None:
        return self._auth.update_user_profile(user_id, name=name, email=email, role=role, bar_enrollment_number=bar_enrollment_number, firm_name=firm_name, secondary_email=secondary_email)

    def save_email_otp(self, email: str, user_id: str, otp_hash: str, expires_at) -> None:
        return self._auth.save_email_otp(email, user_id, otp_hash, expires_at)

    def get_latest_email_otp(self, email: str) -> dict | None:
        return self._auth.get_latest_email_otp(email)

    def get_latest_email_otp_for_user(self, user_id: str) -> dict | None:
        return self._auth.get_latest_email_otp_for_user(user_id)

    def increment_email_otp_attempts(self, otp_id: int) -> None:
        return self._auth.increment_email_otp_attempts(otp_id)

    def mark_email_otp_used(self, otp_id: int) -> None:
        return self._auth.mark_email_otp_used(otp_id)

    def set_email_verified(self, user_id: str, email: str) -> dict | None:
        return self._auth.set_email_verified(user_id, email)

    # ── Tracked cases ────────────────────────────────────────────────────────

    def add_tracked_case(self, user_id: str, case_ref: str, **kwargs: Any) -> int:
        now = datetime.utcnow().isoformat()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO tracked_cases
                  (user_id, case_ref, court_no, bench_label, judges_json,
                   list_date, serial_no, petitioner, respondent, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, case_ref) DO UPDATE SET
                  court_no    = excluded.court_no,
                  bench_label = excluded.bench_label,
                  judges_json = excluded.judges_json,
                  list_date   = excluded.list_date,
                  serial_no   = excluded.serial_no,
                  petitioner  = excluded.petitioner,
                  respondent  = excluded.respondent
                """,
                (
                    user_id,
                    case_ref,
                    kwargs.get("court_no"),
                    kwargs.get("bench_label"),
                    kwargs.get("judges_json"),
                    kwargs.get("list_date"),
                    kwargs.get("serial_no"),
                    kwargs.get("petitioner"),
                    kwargs.get("respondent"),
                    now,
                ),
            )
            row = con.execute(
                "SELECT id FROM tracked_cases WHERE user_id=? AND case_ref=?",
                (user_id, case_ref),
            ).fetchone()
            return int(row["id"])

    def list_tracked_cases(self, user_id: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT
                  tc.*,
                  (SELECT MAX(cc.list_date)
                     FROM causelist_case cc
                    WHERE cc.case_ref = tc.case_ref) AS last_seen_date,
                  (SELECT cc.court_no
                     FROM causelist_case cc
                    WHERE cc.case_ref = tc.case_ref
                    ORDER BY cc.list_date DESC
                    LIMIT 1) AS last_seen_court,
                  (SELECT MIN(cc.list_date)
                     FROM causelist_case cc
                    WHERE cc.case_ref = tc.case_ref
                      AND cc.list_date > date('now')) AS next_hearing_date
                FROM tracked_cases tc
                WHERE tc.user_id = ?
                ORDER BY tc.added_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_tracked_case(self, user_id: str, case_ref: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM tracked_cases WHERE user_id=? AND case_ref=?",
                (user_id, case_ref),
            ).fetchone()
            return dict(row) if row else None

    def remove_tracked_case(self, user_id: str, case_ref: str) -> bool:
        with self.connect() as con:
            cur = con.execute(
                "DELETE FROM tracked_cases WHERE user_id=? AND case_ref=?",
                (user_id, case_ref),
            )
            return cur.rowcount > 0

    def set_case_alert(
        self, user_id: str, case_ref: str, alert_serial: int, look_ahead: int
    ) -> bool:
        with self.connect() as con:
            cur = con.execute(
                """
                UPDATE tracked_cases
                   SET alert_active=1, alert_serial=?, look_ahead=?
                 WHERE user_id=? AND case_ref=?
                """,
                (alert_serial, look_ahead, user_id, case_ref),
            )
            return cur.rowcount > 0

    def clear_case_alert(self, user_id: str, case_ref: str) -> bool:
        with self.connect() as con:
            cur = con.execute(
                "UPDATE tracked_cases SET alert_active=0 WHERE user_id=? AND case_ref=?",
                (user_id, case_ref),
            )
            return cur.rowcount > 0

    def get_courts_with_active_case_alerts(self, today: str) -> set[str]:
        """Return court numbers that currently have active serial alerts.

        Used by the monitor's serial-alert checker to avoid unnecessary per-row
        DB lookups when no alerts exist for a given court.
        """
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT court_no
                FROM tracked_cases
                WHERE court_no IS NOT NULL
                  AND court_no <> ''
                  AND alert_active=1
                  AND alert_serial IS NOT NULL
                  AND (alerted_at IS NULL OR alerted_at < ?)
                """,
                (today,),
            ).fetchall()
            return {str(r["court_no"]).strip() for r in rows if r["court_no"]}

    def list_active_case_alerts(self, court_no: str, today: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM tracked_cases
                WHERE court_no=?
                  AND alert_active=1
                  AND alert_serial IS NOT NULL
                  AND (alerted_at IS NULL OR alerted_at < ?)
                """,
                (court_no, today),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_case_alerted_at(self, user_id: str, case_ref: str, alerted_at: str) -> None:
        with self.connect() as con:
            con.execute(
                "UPDATE tracked_cases SET alerted_at=? WHERE user_id=? AND case_ref=?",
                (alerted_at, user_id, case_ref),
            )

    def log_case_notification(
        self, tracked_case_id: int, payload: str, status: str = "sent"
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO notification_log (tracked_case_id, sent_at, payload, status)
                VALUES (?, ?, ?, ?)
                """,
                (tracked_case_id, now, payload, status),
            )

    def get_notification_prefs(self, user_id: str) -> dict:
        return self._auth.get_notification_prefs(user_id)

    def update_notification_prefs(self, user_id: str, prefs: dict) -> dict:
        return self._auth.update_notification_prefs(user_id, prefs)

    # ── Timeline delegation ───────────────────────────────────────────────────

    def upsert_snapshot(self, case_ref: str, list_date: str, data_json: str, hash_val: str) -> bool:
        return self._timeline.upsert_snapshot(case_ref, list_date, data_json, hash_val)

    def get_last_snapshot(self, case_ref: str) -> dict | None:
        return self._timeline.get_last_snapshot(case_ref)

    def insert_timeline_event(
        self,
        user_id: str,
        case_ref: str,
        event_type: str,
        event_date: str,
        change_summary: str | None = None,
    ) -> None:
        return self._timeline.insert_timeline_event(
            user_id, case_ref, event_type, event_date, change_summary
        )

    def get_timeline(self, user_id: str, case_ref: str, limit: int = 50) -> list[dict]:
        return self._timeline.get_timeline(user_id, case_ref, limit)

    def get_all_tracked_case_refs(self) -> list[str]:
        return self._timeline.get_all_tracked_case_refs()

    def get_users_tracking(self, case_ref: str) -> list[str]:
        return self._timeline.get_users_tracking(case_ref)

    def has_causelist_alert_today(self, user_id: str, case_ref: str, event_date: str) -> bool:
        return self._timeline.has_causelist_alert_today(user_id, case_ref, event_date)

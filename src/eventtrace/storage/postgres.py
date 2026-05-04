from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator

from ..domain.models import EventTrace
from .repositories.auth import PostgresAuthRepository
from .repositories.causelist import PostgresCauselistRepository
from .repositories.events import PostgresEventsRepository
from .repositories.subscriptions import PostgresSubscriptionsRepository

log = logging.getLogger(__name__)

# ── PostgreSQL backend ────────────────────────────────────────────────────────

class PostgresDB:
    """PostgreSQL-backed store with the same public interface as DB."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None
        self._pool_lock = threading.Lock()
        self._events = PostgresEventsRepository(self._cursor)
        self._subscriptions = PostgresSubscriptionsRepository(self._cursor)
        self._causelist = PostgresCauselistRepository(self._cursor)
        self._auth = PostgresAuthRepository(self._cursor)

    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is not None:
                return self._pool
            import psycopg2  # type: ignore[import]
            import psycopg2.pool  # type: ignore[import]
            for attempt in range(9):
                try:
                    self._pool = psycopg2.pool.ThreadedConnectionPool(1, 5, self._dsn)
                    return self._pool
                except psycopg2.OperationalError as exc:
                    log.warning("Postgres not ready (attempt %d/9): %s — retrying in 3s", attempt + 1, exc)
                    time.sleep(3)
            self._pool = psycopg2.pool.ThreadedConnectionPool(1, 5, self._dsn)
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
            # ── Auth / subscription model ────────────────────────────────────
            """
            CREATE TABLE IF NOT EXISTS profiles (
              id          TEXT PRIMARY KEY,
              email       TEXT,
              display_name TEXT,
              role        TEXT NOT NULL DEFAULT 'client',
              tier        TEXT NOT NULL DEFAULT 'free',
              phone       TEXT,
              created_at  TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tracked_cases (
              id              SERIAL PRIMARY KEY,
              user_id         TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
              case_ref        TEXT NOT NULL,
              case_type       TEXT,
              case_number     TEXT,
              case_year       INTEGER,
              petitioner      TEXT,
              respondent      TEXT,
              notes           TEXT,
              notify_whatsapp INTEGER NOT NULL DEFAULT 0,
              notify_email    INTEGER NOT NULL DEFAULT 1,
              created_at      TEXT NOT NULL,
              UNIQUE(user_id, case_ref)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tracked_cases_user ON tracked_cases(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_tracked_cases_ref ON tracked_cases(case_ref)",
            # ── Phone-OTP auth ────────────────────────────────────────────────
            """
            CREATE TABLE IF NOT EXISTS users (
              id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
              phone       TEXT NOT NULL UNIQUE,
              email       TEXT,
              name        TEXT,
              role        TEXT NOT NULL DEFAULT 'client',
              tier        TEXT NOT NULL DEFAULT 'free',
              verified    INTEGER NOT NULL DEFAULT 0,
              created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)",
            """
            CREATE TABLE IF NOT EXISTS phone_otps (
              id          SERIAL PRIMARY KEY,
              phone       TEXT NOT NULL,
              otp_hash    TEXT NOT NULL,
              expires_at  TIMESTAMPTZ NOT NULL,
              attempts    INTEGER NOT NULL DEFAULT 0,
              used        INTEGER NOT NULL DEFAULT 0,
              created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_phone_otps_phone ON phone_otps(phone)",
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

    # ── Events delegation ────────────────────────────────────────────────────

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        return self._events.upsert_current_state(court_id, row, seen_time)

    def get_field_state(self, court_id: str, field_name: str) -> dict[str, Any] | None:
        return self._events.get_field_state(court_id, field_name)

    def upsert_field_state(self, court_id: str, field_name: str, value: str | None, start_time: datetime, last_seen_time: datetime) -> None:
        return self._events.upsert_field_state(court_id, field_name, value, start_time, last_seen_time)

    def touch_field_state(self, court_id: str, field_name: str, last_seen_time: datetime) -> None:
        return self._events.touch_field_state(court_id, field_name, last_seen_time)

    def insert_event_trace(self, trace: EventTrace, observed_time: datetime) -> None:
        return self._events.insert_event_trace(trace, observed_time)

    def insert_change(self, change: EventTrace, observed_time: datetime) -> None:
        return self._events.insert_change(change, observed_time)

    def list_current_state(self) -> list[dict[str, Any]]:
        return self._events.list_current_state()

    def list_event_traces(self, limit: int = 200, court_id: str | None = None) -> list[dict[str, Any]]:
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

    def upsert_vc_zoom_link(self, date: str, room_no: str, zoom_url: str, scraped_at: datetime) -> None:
        return self._events.upsert_vc_zoom_link(date, room_no, zoom_url, scraped_at)

    def get_vc_zoom_links(self, date: str) -> dict[str, str]:
        return self._events.get_vc_zoom_links(date)

    def list_vc_dates(self) -> list[str]:
        return self._events.list_vc_dates()

    # ── Subscriptions delegation ─────────────────────────────────────────────

    def add_subscription(self, telegram_id: str, room_no: str, target_serial: int, look_ahead: int, hearing_date: str | None = None, contact_type: str = "telegram", display_name: str | None = None, phone: str | None = None) -> int:
        return self._subscriptions.add_subscription(telegram_id, room_no, target_serial, look_ahead, hearing_date, contact_type, display_name, phone)

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

    def get_causelist_bench(self, list_date: str, court_no: str) -> dict[str, Any] | None:
        return self._causelist.get_causelist_bench(list_date, court_no)

    def list_causelist_benches(self, list_date: str) -> list[dict[str, Any]]:
        return self._causelist.list_causelist_benches(list_date)

    def list_causelist_cases(self, list_date: str, court_no: str) -> list[dict[str, Any]]:
        return self._causelist.list_causelist_cases(list_date, court_no)

    def get_causelist_case_by_serial(self, list_date: str, court_no: str, serial_no: int) -> dict[str, Any] | None:
        return self._causelist.get_causelist_case_by_serial(list_date, court_no, serial_no)

    def search_causelist_cases(self, case_ref: str | None = None, advocate: str | None = None, party: str | None = None, judge: str | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._causelist.search_causelist_cases(case_ref, advocate, party, judge, date_from, date_to, limit)

    def list_causelist_dates(self) -> list[str]:
        return self._causelist.list_causelist_dates()

    def list_causelist_prefixes(self) -> list[str]:
        return self._causelist.list_causelist_prefixes()

    def store_causelist(self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None) -> int:
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

    def update_user_profile(self, user_id: str, name: str | None, email: str | None) -> dict | None:
        return self._auth.update_user_profile(user_id, name, email)

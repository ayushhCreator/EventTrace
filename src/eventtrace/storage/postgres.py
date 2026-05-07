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
from .repositories.timeline import PostgresTimelineRepository

log = logging.getLogger(__name__)


def _default_prefs() -> dict:
    return {
        "whatsapp": True,
        "email": True,
        "serial_alerts": True,
        "causelist_alerts": True,
        "change_alerts": True,
    }


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
        self._timeline = PostgresTimelineRepository(self._cursor)

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
                    log.warning(
                        "Postgres not ready (attempt %d/9): %s — retrying in 3s", attempt + 1, exc
                    )
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
            CREATE TABLE IF NOT EXISTS tracked_cases (
              id           SERIAL PRIMARY KEY,
              user_id      UUID NOT NULL,
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
            """
            CREATE TABLE IF NOT EXISTS case_snapshots (
              id         SERIAL PRIMARY KEY,
              case_ref   TEXT NOT NULL,
              list_date  TEXT NOT NULL,
              data_json  TEXT NOT NULL,
              hash       TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE(case_ref, list_date)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_case_snapshots_ref ON case_snapshots(case_ref)",
            "CREATE INDEX IF NOT EXISTS idx_case_snapshots_date ON case_snapshots(list_date)",
            """
            CREATE TABLE IF NOT EXISTS case_timeline_events (
              id             SERIAL PRIMARY KEY,
              user_id        UUID NOT NULL,
              case_ref       TEXT NOT NULL,
              event_type     TEXT NOT NULL,
              event_date     TEXT NOT NULL,
              change_summary TEXT,
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_cte_user_ref ON case_timeline_events(user_id, case_ref)",
            "CREATE INDEX IF NOT EXISTS idx_cte_event_date ON case_timeline_events(event_date)",
            # ── Matters (case billing registration) ──────────────────────────
            """
            CREATE TABLE IF NOT EXISTS matter (
              id              SERIAL PRIMARY KEY,
              user_id         UUID NOT NULL,
              case_ref        TEXT NOT NULL,
              case_title      TEXT,
              case_type       TEXT,
              case_number     TEXT,
              case_year       INTEGER,
              court_no        TEXT,
              petitioner      TEXT,
              respondent      TEXT,
              status          TEXT NOT NULL DEFAULT 'active',
              billing_mode    TEXT NOT NULL DEFAULT 'appearance',
              fee_per_appearance NUMERIC(12,2),
              notes           TEXT,
              opened_at       DATE,
              closed_at       DATE,
              created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE(user_id, case_ref)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_matter_user ON matter(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_matter_case_ref ON matter(case_ref)",
            "CREATE INDEX IF NOT EXISTS idx_matter_status ON matter(user_id, status)",
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

            # Non-destructive column migrations for tracked_cases (safe to re-run)
            for _col in [
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS court_no TEXT",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS bench_label TEXT",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS judges_json TEXT",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS list_date TEXT",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS serial_no INTEGER",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS petitioner TEXT",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS respondent TEXT",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS alert_active INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS alert_serial INTEGER",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS look_ahead INTEGER NOT NULL DEFAULT 5",
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS added_at TEXT NOT NULL DEFAULT NOW()::TEXT",
            ]:
                try:
                    cur.execute(_col)
                except Exception:
                    pass

            # Additional column migrations
            for _col in [
                "ALTER TABLE tracked_cases ADD COLUMN IF NOT EXISTS alerted_at TEXT",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_prefs TEXT",
                "ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS tracked_case_id INTEGER",
                "ALTER TABLE notification_log ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'sent'",
            ]:
                try:
                    cur.execute(_col)
                except Exception:
                    pass

            # Drop stale FK to profiles (if still present on old DBs). No FK re-added:
            # user_id is TEXT on old tables, UUID on new — JWT auth enforces ownership.
            try:
                cur.execute(
                    "ALTER TABLE tracked_cases DROP CONSTRAINT IF EXISTS tracked_cases_user_id_fkey"
                )
            except Exception:
                pass

            # ── causelist_bench schema migration ─────────────────────────────
            # Step 1: add source_id column
            try:
                cur.execute("ALTER TABLE causelist_bench ADD COLUMN IF NOT EXISTS source_id TEXT")
                cur.execute("ALTER TABLE causelist_bench ADD COLUMN IF NOT EXISTS at_time TEXT")
                cur.execute("ALTER TABLE causelist_bench ADD COLUMN IF NOT EXISTS floor TEXT")
                cur.execute("ALTER TABLE causelist_bench ADD COLUMN IF NOT EXISTS building TEXT")
            except Exception:
                pass

            # Step 2: normalise side/list_type values and backfill source_id.
            # Historical data has mixed-case values, non-breaking spaces, and
            # NULL source_id. Canonicalise everything so ON CONFLICT works.
            try:
                cur.execute(r"""
                    UPDATE causelist_bench
                    SET side = CASE
                        WHEN regexp_replace(upper(side), '\s+', ' ', 'g') LIKE '%ORIGINAL%'
                            THEN 'ORIGINAL SIDE'
                        ELSE 'APPELLATE SIDE'
                    END
                    WHERE side IS NULL
                       OR upper(side) != side
                       OR side LIKE '%' || chr(160) || '%'
                """)
                cur.execute("""
                    UPDATE causelist_bench
                    SET list_type = upper(list_type)
                    WHERE list_type IS NOT NULL AND upper(list_type) != list_type
                """)
                cur.execute("""
                    UPDATE causelist_bench
                    SET list_type = 'DAILY'
                    WHERE list_type IS NULL
                """)
                cur.execute("""
                    UPDATE causelist_bench
                    SET source_id = CASE
                        WHEN side = 'ORIGINAL SIDE' THEN 'original_unknown'
                        ELSE 'appellate_static'
                    END
                    WHERE source_id IS NULL
                """)
            except Exception:
                pass

            # Step 3: drop old 2-column unique constraint and replace with 4-column one.
            # We find the constraint by searching pg_constraint regardless of its
            # auto-generated name, so this survives Supabase / Railway naming quirks.
            try:
                cur.execute("""
                    DO $$
                    DECLARE
                        cname TEXT;
                    BEGIN
                        -- Find any unique constraint on causelist_bench that covers
                        -- exactly (list_date, court_no) — 2 columns.
                        SELECT c.conname INTO cname
                        FROM pg_constraint c
                        JOIN pg_class t ON t.oid = c.conrelid
                        WHERE t.relname = 'causelist_bench'
                          AND c.contype = 'u'
                          AND array_length(c.conkey, 1) = 2
                        LIMIT 1;

                        IF cname IS NOT NULL THEN
                            EXECUTE format('ALTER TABLE causelist_bench DROP CONSTRAINT %I', cname);
                        END IF;

                        -- Add new 4-column constraint (idempotent via IF NOT EXISTS check)
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint c
                            JOIN pg_class t ON t.oid = c.conrelid
                            WHERE t.relname = 'causelist_bench'
                              AND c.contype = 'u'
                              AND array_length(c.conkey, 1) = 4
                        ) THEN
                            ALTER TABLE causelist_bench
                                ADD CONSTRAINT causelist_bench_unique_source
                                UNIQUE (list_date, court_no, side, list_type);
                        END IF;
                    END $$;
                """)
            except Exception:
                pass

    # ── Events delegation ────────────────────────────────────────────────────

    def upsert_current_state(self, court_id: str, row: dict[str, Any], seen_time: datetime) -> None:
        return self._events.upsert_current_state(court_id, row, seen_time)

    def get_field_state(self, court_id: str, field_name: str) -> dict[str, Any] | None:
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

    def is_causelist_source_scraped(self, list_date: str, source_id: str) -> bool:
        return self._causelist.is_causelist_source_scraped(list_date, source_id)

    def list_causelist_dates(self) -> list[str]:
        return self._causelist.list_causelist_dates()

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

    def update_user_profile(self, user_id: str, name: str | None, email: str | None) -> dict | None:
        return self._auth.update_user_profile(user_id, name, email)

    # ── Tracked cases ────────────────────────────────────────────────────────

    def add_tracked_case(self, user_id: str, case_ref: str, **kwargs: Any) -> int:
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO tracked_cases
                  (user_id, case_ref, court_no, bench_label, judges_json,
                   list_date, serial_no, petitioner, respondent, added_at,
                   created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, case_ref) DO UPDATE SET
                  court_no    = EXCLUDED.court_no,
                  bench_label = EXCLUDED.bench_label,
                  judges_json = EXCLUDED.judges_json,
                  list_date   = EXCLUDED.list_date,
                  serial_no   = EXCLUDED.serial_no,
                  petitioner  = EXCLUDED.petitioner,
                  respondent  = EXCLUDED.respondent
                RETURNING id
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
            row = cur.fetchone()
            return int(row["id"])

    def list_tracked_cases(self, user_id: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
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
                      AND cc.list_date > CURRENT_DATE::TEXT) AS next_hearing_date
                FROM tracked_cases tc
                WHERE tc.user_id = %s
                ORDER BY tc.added_at DESC
                """,
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_tracked_case(self, user_id: str, case_ref: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM tracked_cases WHERE user_id=%s AND case_ref=%s",
                (user_id, case_ref),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def remove_tracked_case(self, user_id: str, case_ref: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM tracked_cases WHERE user_id=%s AND case_ref=%s",
                (user_id, case_ref),
            )
            return cur.rowcount > 0

    def set_case_alert(
        self, user_id: str, case_ref: str, alert_serial: int, look_ahead: int
    ) -> bool:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE tracked_cases
                   SET alert_active=1, alert_serial=%s, look_ahead=%s
                 WHERE user_id=%s AND case_ref=%s
                """,
                (alert_serial, look_ahead, user_id, case_ref),
            )
            return cur.rowcount > 0

    def clear_case_alert(self, user_id: str, case_ref: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE tracked_cases SET alert_active=0 WHERE user_id=%s AND case_ref=%s",
                (user_id, case_ref),
            )
            return cur.rowcount > 0

    def get_courts_with_active_case_alerts(self, today: str) -> set[str]:
        """Return court numbers that currently have active serial alerts.

        Used by the monitor's serial-alert checker to avoid unnecessary per-row
        DB lookups when no alerts exist for a given court.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT court_no
                FROM tracked_cases
                WHERE court_no IS NOT NULL
                  AND court_no <> ''
                  AND alert_active=1
                  AND alert_serial IS NOT NULL
                  AND (alerted_at IS NULL OR alerted_at < %s)
                """,
                (today,),
            )
            rows = cur.fetchall()
        return {str(r["court_no"]).strip() for r in rows if r.get("court_no")}

    def list_active_case_alerts(self, court_no: str, today: str) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM tracked_cases
                WHERE court_no=%s
                  AND alert_active=1
                  AND alert_serial IS NOT NULL
                  AND (alerted_at IS NULL OR alerted_at < %s)
                """,
                (court_no, today),
            )
            return [dict(r) for r in cur.fetchall()]

    def update_case_alerted_at(self, user_id: str, case_ref: str, alerted_at: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE tracked_cases SET alerted_at=%s WHERE user_id=%s AND case_ref=%s",
                (alerted_at, user_id, case_ref),
            )

    def log_case_notification(
        self, tracked_case_id: int, payload: str, status: str = "sent"
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO notification_log (tracked_case_id, sent_at, payload, status)
                VALUES (%s, NOW(), %s, %s)
                """,
                (tracked_case_id, payload, status),
            )

    def get_notification_prefs(self, user_id: str) -> dict:
        import json

        with self._cursor() as cur:
            cur.execute(
                "SELECT notification_prefs FROM users WHERE id=%s",
                (user_id,),
            )
            row = cur.fetchone()
        if not row or not row["notification_prefs"]:
            return _default_prefs()
        try:
            return {**_default_prefs(), **json.loads(row["notification_prefs"])}
        except Exception:
            return _default_prefs()

    def update_notification_prefs(self, user_id: str, prefs: dict) -> dict:
        import json

        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET notification_prefs=%s WHERE id=%s",
                (json.dumps(prefs), user_id),
            )
        return prefs

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

    # ── Matter (billing registration) ────────────────────────────────────────

    def list_matters(self, user_id: str, status: str | None = None) -> list[dict]:
        with self._cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM matter WHERE user_id=%s AND status=%s ORDER BY created_at DESC",
                    (user_id, status),
                )
            else:
                cur.execute(
                    "SELECT * FROM matter WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,),
                )
            return [dict(r) for r in cur.fetchall()]

    def get_matter(self, user_id: str, matter_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM matter WHERE id=%s AND user_id=%s",
                (matter_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def create_matter(
        self,
        user_id: str,
        case_ref: str,
        case_title: str | None = None,
        case_type: str | None = None,
        case_number: str | None = None,
        case_year: int | None = None,
        court_no: str | None = None,
        petitioner: str | None = None,
        respondent: str | None = None,
        billing_mode: str = "appearance",
        fee_per_appearance: float | None = None,
        notes: str | None = None,
        opened_at: str | None = None,
    ) -> dict:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO matter (
                    user_id, case_ref, case_title, case_type, case_number, case_year,
                    court_no, petitioner, respondent, billing_mode, fee_per_appearance,
                    notes, opened_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (user_id, case_ref)
                DO UPDATE SET
                    case_title=EXCLUDED.case_title,
                    case_type=EXCLUDED.case_type,
                    case_number=EXCLUDED.case_number,
                    case_year=EXCLUDED.case_year,
                    court_no=EXCLUDED.court_no,
                    petitioner=EXCLUDED.petitioner,
                    respondent=EXCLUDED.respondent,
                    billing_mode=EXCLUDED.billing_mode,
                    fee_per_appearance=EXCLUDED.fee_per_appearance,
                    notes=EXCLUDED.notes,
                    opened_at=COALESCE(EXCLUDED.opened_at, matter.opened_at)
                RETURNING *
                """,
                (
                    user_id, case_ref, case_title, case_type, case_number, case_year,
                    court_no, petitioner, respondent, billing_mode, fee_per_appearance,
                    notes, opened_at,
                ),
            )
            return dict(cur.fetchone())

    def update_matter(self, user_id: str, matter_id: int, **fields) -> dict | None:
        allowed = {
            "case_title", "court_no", "petitioner", "respondent",
            "billing_mode", "fee_per_appearance", "notes",
            "status", "opened_at", "closed_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_matter(user_id, matter_id)
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE matter SET {set_clause} WHERE id=%s AND user_id=%s RETURNING *",
                (*updates.values(), matter_id, user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_matter(self, user_id: str, matter_id: int) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM matter WHERE id=%s AND user_id=%s",
                (matter_id, user_id),
            )
            return cur.rowcount > 0

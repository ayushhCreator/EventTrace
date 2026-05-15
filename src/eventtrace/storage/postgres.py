from __future__ import annotations

import structlog
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from typing import Any, Generator

from sqlalchemy import create_engine

from ..domain.models import EventTrace
from .repositories.auth_alchemy import SQLAlchemyAuthRepository
from .repositories.causelist_alchemy import SQLAlchemyCauselistRepository
from .repositories.events_alchemy import SQLAlchemyEventsRepository
from .repositories.notification_alchemy import SQLAlchemyNotificationRepository
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


# ── PostgreSQL backend ────────────────────────────────────────────────────────


class PostgresDB:
    """PostgreSQL-backed store with the same public interface as DB."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None
        self._pool_lock = threading.Lock()
        # SQLAlchemy 2.0 requires "postgresql://" not "postgres://" (Railway uses the latter)
        _sa_url = (
            dsn.replace("postgres://", "postgresql://", 1) if dsn.startswith("postgres://") else dsn
        )
        self._engine = create_engine(_sa_url, pool_size=5, max_overflow=10)
        self._events = SQLAlchemyEventsRepository(self._engine)
        self._subscriptions = SQLAlchemySubscriptionsRepository(self._engine)
        self._causelist = SQLAlchemyCauselistRepository(self._engine)
        self._auth = SQLAlchemyAuthRepository(self._engine)
        self._timeline = SQLAlchemyTimelineRepository(self._engine)
        self._notifications = SQLAlchemyNotificationRepository(self._engine)

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
        """Schema is managed by SQLAlchemy models and Alembic migrations."""
        import structlog
        structlog.get_logger().info("ensure_schema: Schema is managed by Alembic. Skipping raw SQL schema creation.")

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
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._causelist.get_causelist_bench(
            list_date, court_no, side=side, list_type=list_type, source_id=source_id
        )

    def list_causelist_benches(
        self,
        list_date: str,
        side: str | None = None,
        list_type: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._causelist.list_causelist_benches(
            list_date, side=side, list_type=list_type, source_id=source_id
        )

    def list_causelist_cases(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
        source_id: str | None = None,
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
        section: str | None = None,
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
            section=section,
            limit=limit,
        )

    def is_causelist_source_scraped(self, list_date: str, source_id: str) -> bool:
        return self._causelist.is_causelist_source_scraped(list_date, source_id)

    def list_causelist_dates(self) -> list[str]:
        return self._causelist.list_causelist_dates()

    def list_causelist_prefixes(self) -> list[str]:
        return self._causelist.list_causelist_prefixes()

    def list_available_list_types(self, list_date: str) -> list[dict]:
        return self._causelist.list_available_list_types(list_date)

    def list_bench_rules(self, bench_id: int) -> list[dict]:
        return self._causelist.list_bench_rules(bench_id)

    def list_judges_for_date(self, list_date: str, side: str | None = None) -> list[dict]:
        return self._causelist.list_judges_for_date(list_date, side)

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        return self._causelist.store_causelist(parsed, scraped_at)

    def get_bench_by_id(self, bench_id: int) -> dict[str, Any] | None:
        return self._causelist.get_bench_by_id(bench_id)

    def list_cases_by_bench_id(self, bench_id: int) -> list[dict[str, Any]]:
        return self._causelist.list_cases_by_bench_id(bench_id)

    # ── Auth delegation ──────────────────────────────────────────────────────

    def get_user_by_phone(self, phone: str) -> dict | None:
        return self._auth.get_user_by_phone(phone)

    def get_user_by_id(self, user_id: str) -> dict | None:
        return self._auth.get_user_by_id(user_id)

    def get_user_by_email(self, email: str) -> dict | None:
        return self._auth.get_user_by_email(email)

    def upsert_user(
        self,
        phone: str,
        name: str | None = None,
        email: str | None = None,
        whatsapp_number: str | None = None,
    ) -> dict:
        return self._auth.upsert_user(phone, name, email, whatsapp_number=whatsapp_number)

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

    def update_user_profile(
        self,
        user_id: str,
        name: str | None = None,
        email: str | None = None,
        whatsapp_number: str | None = None,
        role: str | None = None,
        bar_enrollment_number: str | None = None,
        firm_name: str | None = None,
        secondary_email: str | None = None,
    ) -> dict | None:
        return self._auth.update_user_profile(
            user_id,
            name=name,
            email=email,
            whatsapp_number=whatsapp_number,
            role=role,
            bar_enrollment_number=bar_enrollment_number,
            firm_name=firm_name,
            secondary_email=secondary_email,
        )

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

    # ── WhatsApp OTP ──────────────────────────────────────────────────────────

    def save_whatsapp_otp(self, whatsapp_number: str, user_id: str, otp_hash: str, expires_at: Any) -> None:
        return self._auth.save_whatsapp_otp(whatsapp_number, user_id, otp_hash, expires_at)

    def get_latest_whatsapp_otp(self, whatsapp_number: str) -> dict | None:
        return self._auth.get_latest_whatsapp_otp(whatsapp_number)

    def get_latest_whatsapp_otp_for_user(self, user_id: str) -> dict | None:
        return self._auth.get_latest_whatsapp_otp_for_user(user_id)

    def increment_whatsapp_otp_attempts(self, otp_id: int) -> None:
        return self._auth.increment_whatsapp_otp_attempts(otp_id)

    def mark_whatsapp_otp_used(self, otp_id: int) -> None:
        return self._auth.mark_whatsapp_otp_used(otp_id)

    def set_whatsapp_verified(self, user_id: str, whatsapp_number: str) -> dict | None:
        return self._auth.set_whatsapp_verified(user_id, whatsapp_number)

    def get_user_stats(self) -> dict:
        return self._auth.get_user_stats()

    def list_all_users_with_stats(self) -> list[dict]:
        return self._auth.list_all_users_with_stats()

    def save_refresh_token(self, user_id: str, token_hash: str, expires_at: str) -> None:
        return self._auth.save_refresh_token(user_id, token_hash, expires_at)

    def get_refresh_token(self, token_hash: str) -> dict | None:
        return self._auth.get_refresh_token(token_hash)

    def revoke_refresh_token(self, token_hash: str) -> None:
        return self._auth.revoke_refresh_token(token_hash)

    def revoke_all_user_refresh_tokens(self, user_id: str) -> None:
        return self._auth.revoke_all_user_refresh_tokens(user_id)

    # ── Tracked cases ────────────────────────────────────────────────────────

    def add_tracked_case(self, user_id: str, case_ref: str, **kwargs: Any) -> int:
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO tracked_cases
                                    (user_id, case_ref, court_no, bench_label, judges_json,
                                     list_date, serial_no, petitioner, respondent,
                                     cino, case_type_id, state_cd, court_code, case_no, case_year,
                                     added_at, alert_active, look_ahead)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 5)
                ON CONFLICT (user_id, case_ref) DO UPDATE SET
                  court_no    = EXCLUDED.court_no,
                  bench_label = EXCLUDED.bench_label,
                  judges_json = EXCLUDED.judges_json,
                  list_date   = EXCLUDED.list_date,
                  serial_no   = EXCLUDED.serial_no,
                  petitioner  = EXCLUDED.petitioner,
                                    respondent  = EXCLUDED.respondent,
                                    cino        = EXCLUDED.cino,
                                    case_type_id = EXCLUDED.case_type_id,
                                    state_cd    = EXCLUDED.state_cd,
                                    court_code  = EXCLUDED.court_code,
                                    case_no     = EXCLUDED.case_no,
                                    case_year   = EXCLUDED.case_year
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
                                        kwargs.get("cino"),
                                        kwargs.get("case_type_id"),
                                        kwargs.get("state_cd"),
                                        kwargs.get("court_code"),
                                        kwargs.get("case_no"),
                                        kwargs.get("case_year"),
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

    def list_tracked_cases_for_refresh(self, limit: int | None = None) -> list[dict]:
        sql = (
            "SELECT * FROM tracked_cases "
            "WHERE cino IS NOT NULL AND cino <> '' "
            "AND case_type_id IS NOT NULL AND case_type_id <> '' "
            "AND state_cd IS NOT NULL AND state_cd <> '' "
            "AND court_code IS NOT NULL AND court_code <> '' "
            "AND case_no IS NOT NULL AND case_no <> '' "
            "AND case_year IS NOT NULL AND case_year <> '' "
            "ORDER BY added_at DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT %s"
            params = (limit,)
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def get_case_history_cache(
        self,
        cino: str,
        state_cd: str,
        court_code: str,
        max_age_seconds: int | None = None,
    ) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT data_json, fetched_at
                FROM case_history_cache
                WHERE cino=%s AND state_cd=%s AND court_code=%s
                """,
                (cino, state_cd, court_code),
            )
            row = cur.fetchone()
            if not row:
                return None
            fetched_at = row["fetched_at"]
            if max_age_seconds is not None:
                try:
                    ts = datetime.fromisoformat(str(fetched_at))
                    if datetime.utcnow() - ts > timedelta(seconds=max_age_seconds):
                        return None
                except Exception:
                    return None
            try:
                data = json.loads(row["data_json"])
            except Exception:
                return None
            data["cached"] = True
            data["cached_at"] = str(fetched_at)
            return data

    def set_case_history_cache(
        self,
        cino: str,
        state_cd: str,
        court_code: str,
        case_type_id: str | None,
        case_no: str | None,
        case_year: str | None,
        data: dict,
    ) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO case_history_cache
                  (cino, state_cd, court_code, case_type_id, case_no, case_year, data_json, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW()::TEXT)
                ON CONFLICT (cino, state_cd, court_code) DO UPDATE SET
                  case_type_id=EXCLUDED.case_type_id,
                  case_no=EXCLUDED.case_no,
                  case_year=EXCLUDED.case_year,
                  data_json=EXCLUDED.data_json,
                  fetched_at=EXCLUDED.fetched_at
                """,
                (cino, state_cd, court_code, case_type_id, case_no, case_year, payload),
            )

    def get_tracked_case(self, user_id: str, case_ref: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM tracked_cases WHERE user_id=%s AND case_ref=%s",
                (user_id, case_ref),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_tracked_case(self, user_id: str, case_ref: str, updates: dict) -> bool:
        allowed = {"cino", "case_type_id", "state_cd", "court_code", "case_no", "case_year",
                   "bench_label", "judges_json", "court_no", "petitioner", "respondent"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE tracked_cases SET {set_clause} WHERE user_id=%s AND case_ref=%s",
                (*fields.values(), user_id, case_ref),
            )
            return cur.rowcount > 0

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
        return self._auth.get_notification_prefs(user_id)

    def update_notification_prefs(self, user_id: str, prefs: dict) -> dict:
        return self._auth.update_notification_prefs(user_id, prefs)

    # ── Notification repository delegation ───────────────────────────────────

    def create_notification_log(
        self,
        user_id: str,
        case_ref: str,
        notification_type: str,
        channel: str,
        message_text: str,
        status: str = "queued",
        tracked_case_id: int | None = None,
        provider: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        return self._notifications.create_notification_log(
            user_id,
            case_ref,
            notification_type,
            channel,
            message_text,
            status=status,
            tracked_case_id=tracked_case_id,
            provider=provider,
            dedup_key=dedup_key,
        )

    def update_notification_status(
        self,
        log_id: int,
        status: str,
        provider_response: str | None = None,
        delivered_at: str | None = None,
        read_at: str | None = None,
    ) -> None:
        return self._notifications.update_notification_status(
            log_id,
            status,
            provider_response=provider_response,
            delivered_at=delivered_at,
            read_at=read_at,
        )

    def get_user_notifications(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        case_ref: str | None = None,
        status: str | None = None,
        unread_only: bool = False,
    ) -> tuple[list[dict], int]:
        return self._notifications.get_user_notifications(
            user_id, limit=limit, offset=offset, case_ref=case_ref, status=status, unread_only=unread_only
        )

    def count_unread_notifications(self, user_id: str) -> int:
        return self._notifications.count_unread_notifications(user_id)

    def mark_notification_read(self, log_id: int, user_id: str) -> bool:
        return self._notifications.mark_notification_read(log_id, user_id)

    def mark_all_notifications_read(self, user_id: str) -> int:
        return self._notifications.mark_all_notifications_read(user_id)

    def get_notification_stats(self, days: int = 7) -> dict:
        return self._notifications.get_notification_stats(days)

    def get_top_searches(self, limit: int = 20) -> list[dict]:
        return self._notifications.get_top_searches(limit)

    def find_notification_log_by_provider_id(self, provider_id: str) -> dict | None:
        return self._notifications.find_notification_log_by_provider_id(provider_id)

    def check_daily_cap(self, user_id: str, channel: str, cap: int) -> bool:
        return self._notifications.check_daily_cap(user_id, channel, cap)

    def check_dedup(self, dedup_key: str, window_hours: int = 1) -> bool:
        return self._notifications.check_dedup(dedup_key, window_hours)

    def enqueue_notification(
        self,
        user_id: str,
        case_ref: str,
        notification_type: str,
        channel: str,
        payload_json: str,
        notification_log_id: int | None = None,
        scheduled_at: str | None = None,
    ) -> int:
        return self._notifications.enqueue_notification(
            user_id,
            case_ref,
            notification_type,
            channel,
            payload_json,
            notification_log_id=notification_log_id,
            scheduled_at=scheduled_at,
        )

    def claim_queued_notifications(
        self,
        worker_id: str,
        batch_size: int = 20,
        lock_seconds: int = 60,
    ) -> list[dict]:
        return self._notifications.claim_queued_notifications(
            worker_id, batch_size=batch_size, lock_seconds=lock_seconds
        )

    def ack_queue_item(self, queue_id: int, success: bool, retry_after_seconds: int = 0) -> None:
        return self._notifications.ack_queue_item(
            queue_id, success, retry_after_seconds=retry_after_seconds
        )

    def get_alert_prefs(self, user_id: str, case_ref: str) -> list[dict]:
        return self._notifications.get_alert_prefs(user_id, case_ref)

    def upsert_alert_prefs(self, user_id: str, case_ref: str, prefs: list[dict]) -> list[dict]:
        return self._notifications.upsert_alert_prefs(user_id, case_ref, prefs)

    def get_alert_pref(self, user_id: str, case_ref: str, trigger_type: str) -> dict | None:
        return self._notifications.get_alert_pref(user_id, case_ref, trigger_type)

    def upsert_single_alert_pref(
        self,
        user_id: str,
        case_ref: str,
        trigger_type: str,
        channel: str | None = None,
        enabled: bool | None = None,
        quiet_hours_start: int | None = None,
        quiet_hours_end: int | None = None,
    ) -> dict:
        return self._notifications.upsert_single_alert_pref(
            user_id,
            case_ref,
            trigger_type,
            channel=channel,
            enabled=enabled,
            quiet_hours_start=quiet_hours_start,
            quiet_hours_end=quiet_hours_end,
        )

    def log_search(
        self,
        query_type: str,
        query_text: str,
        result_count: int | None = None,
        user_id: str | None = None,
        court_source: str | None = None,
    ) -> None:
        return self._notifications.log_search(
            query_type,
            query_text,
            result_count=result_count,
            user_id=user_id,
            court_source=court_source,
        )

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
                    user_id,
                    case_ref,
                    case_title,
                    case_type,
                    case_number,
                    case_year,
                    court_no,
                    petitioner,
                    respondent,
                    billing_mode,
                    fee_per_appearance,
                    notes,
                    opened_at,
                ),
            )
            return dict(cur.fetchone())

    def update_matter(self, user_id: str, matter_id: int, **fields) -> dict | None:
        allowed = {
            "case_title",
            "court_no",
            "petitioner",
            "respondent",
            "billing_mode",
            "fee_per_appearance",
            "notes",
            "status",
            "opened_at",
            "closed_at",
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

    # ── eCourts case type map ─────────────────────────────────────────────────

    def upsert_ecourts_type(
        self, state_cd: str, court_code: str, type_id: str, type_name: str,
        prefix: str | None = None,
    ) -> None:
        now = __import__("datetime").datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO ecourts_case_type_map
                  (state_cd, court_code, type_id, type_name, prefix, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (state_cd, court_code, type_id) DO UPDATE SET
                  type_name = EXCLUDED.type_name,
                  prefix    = COALESCE(EXCLUDED.prefix, ecourts_case_type_map.prefix),
                  fetched_at = EXCLUDED.fetched_at
                """,
                (state_cd, court_code, type_id, type_name, prefix, now),
            )

    def set_ecourts_type_prefix(
        self, state_cd: str, court_code: str, type_id: str, prefix: str
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE ecourts_case_type_map SET prefix=%s WHERE state_cd=%s AND court_code=%s AND type_id=%s",
                (prefix, state_cd, court_code, type_id),
            )

    def get_ecourts_type_id(
        self, state_cd: str, court_code: str, prefix: str
    ) -> str | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT type_id FROM ecourts_case_type_map WHERE state_cd=%s AND court_code=%s AND UPPER(prefix)=UPPER(%s) LIMIT 1",
                (state_cd, court_code, prefix),
            )
            row = cur.fetchone()
            return row["type_id"] if row else None

    def list_ecourts_types(
        self, state_cd: str, court_code: str
    ) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT type_id, type_name, prefix FROM ecourts_case_type_map WHERE state_cd=%s AND court_code=%s ORDER BY type_id",
                (state_cd, court_code),
            )
            return [dict(r) for r in cur.fetchall()]

    def ecourts_types_populated(self, state_cd: str, court_code: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM ecourts_case_type_map WHERE state_cd=%s AND court_code=%s LIMIT 1",
                (state_cd, court_code),
            )
            return cur.fetchone() is not None

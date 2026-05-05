"""Repositories for case_snapshots and case_timeline_events tables."""

from __future__ import annotations

from ...common.time import iso, utc_now


class SQLiteTimelineRepository:
    def __init__(self, connect_fn) -> None:
        self._connect = connect_fn

    def upsert_snapshot(self, case_ref: str, list_date: str, data_json: str, hash_val: str) -> bool:
        now = iso(utc_now())
        with self._connect() as con:
            existing = con.execute(
                "SELECT hash FROM case_snapshots WHERE case_ref=? AND list_date=?",
                (case_ref, list_date),
            ).fetchone()
            if existing and existing["hash"] == hash_val:
                return False
            con.execute(
                """
                INSERT INTO case_snapshots (case_ref, list_date, data_json, hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_ref, list_date) DO UPDATE SET
                  data_json  = excluded.data_json,
                  hash       = excluded.hash,
                  created_at = excluded.created_at
                """,
                (case_ref, list_date, data_json, hash_val, now),
            )
            return True

    def get_last_snapshot(self, case_ref: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM case_snapshots WHERE case_ref=? ORDER BY list_date DESC LIMIT 1",
                (case_ref,),
            ).fetchone()
            return dict(row) if row else None

    def insert_timeline_event(
        self,
        user_id: str,
        case_ref: str,
        event_type: str,
        event_date: str,
        change_summary: str | None = None,
    ) -> None:
        now = iso(utc_now())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO case_timeline_events
                  (user_id, case_ref, event_type, event_date, change_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, case_ref, event_type, event_date, change_summary, now),
            )

    def get_timeline(self, user_id: str, case_ref: str, limit: int = 50) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT * FROM case_timeline_events
                WHERE user_id=? AND case_ref=?
                ORDER BY event_date DESC, id DESC
                LIMIT ?
                """,
                (user_id, case_ref, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_tracked_case_refs(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute("SELECT DISTINCT case_ref FROM tracked_cases").fetchall()
            return [r["case_ref"] for r in rows]

    def get_users_tracking(self, case_ref: str) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT user_id FROM tracked_cases WHERE case_ref=?",
                (case_ref,),
            ).fetchall()
            return [r["user_id"] for r in rows]

    def has_causelist_alert_today(self, user_id: str, case_ref: str, event_date: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id FROM case_timeline_events
                WHERE user_id=? AND case_ref=? AND event_type='case_in_causelist' AND event_date=?
                LIMIT 1
                """,
                (user_id, case_ref, event_date),
            ).fetchone()
            return row is not None


class PostgresTimelineRepository:
    def __init__(self, cursor_ctx) -> None:
        self._cursor = cursor_ctx

    def upsert_snapshot(self, case_ref: str, list_date: str, data_json: str, hash_val: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT hash FROM case_snapshots WHERE case_ref=%s AND list_date=%s",
                (case_ref, list_date),
            )
            existing = cur.fetchone()
            if existing and existing["hash"] == hash_val:
                return False
            cur.execute(
                """
                INSERT INTO case_snapshots (case_ref, list_date, data_json, hash, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (case_ref, list_date) DO UPDATE SET
                  data_json  = EXCLUDED.data_json,
                  hash       = EXCLUDED.hash,
                  created_at = NOW()
                """,
                (case_ref, list_date, data_json, hash_val),
            )
            return True

    def get_last_snapshot(self, case_ref: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM case_snapshots WHERE case_ref=%s ORDER BY list_date DESC LIMIT 1",
                (case_ref,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def insert_timeline_event(
        self,
        user_id: str,
        case_ref: str,
        event_type: str,
        event_date: str,
        change_summary: str | None = None,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO case_timeline_events
                  (user_id, case_ref, event_type, event_date, change_summary, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (user_id, case_ref, event_type, event_date, change_summary),
            )

    def get_timeline(self, user_id: str, case_ref: str, limit: int = 50) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT * FROM case_timeline_events
                WHERE user_id=%s AND case_ref=%s
                ORDER BY event_date DESC, id DESC
                LIMIT %s
                """,
                (user_id, case_ref, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_all_tracked_case_refs(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute("SELECT DISTINCT case_ref FROM tracked_cases")
            return [r["case_ref"] for r in cur.fetchall()]

    def get_users_tracking(self, case_ref: str) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT DISTINCT user_id FROM tracked_cases WHERE case_ref=%s",
                (case_ref,),
            )
            return [r["user_id"] for r in cur.fetchall()]

    def has_causelist_alert_today(self, user_id: str, case_ref: str, event_date: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id FROM case_timeline_events
                WHERE user_id=%s AND case_ref=%s AND event_type='case_in_causelist' AND event_date=%s
                LIMIT 1
                """,
                (user_id, case_ref, event_date),
            )
            return cur.fetchone() is not None

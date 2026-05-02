#!/usr/bin/env python3
"""
Migrate all data from local SQLite to a target Postgres URL.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        --sqlite data/eventtrace.sqlite3 \
        --postgres "postgresql://user:pass@host:5432/db"

The script is idempotent — safe to re-run (uses ON CONFLICT DO NOTHING for most
tables, and skips event_trace rows that already exist by id range check).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


@contextmanager
def pg_cursor(conn):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def migrate_current_state(sq: sqlite3.Connection, pg) -> int:
    rows = sq.execute("SELECT court_id, data_json, last_seen_time FROM current_state").fetchall()
    if not rows:
        return 0
    with pg_cursor(pg) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO current_state(court_id, data_json, last_seen_time)
            VALUES %s
            ON CONFLICT(court_id) DO UPDATE SET
              data_json=EXCLUDED.data_json,
              last_seen_time=EXCLUDED.last_seen_time
            """,
            [(r["court_id"], r["data_json"], r["last_seen_time"]) for r in rows],
        )
    return len(rows)


def migrate_field_state(sq: sqlite3.Connection, pg) -> int:
    rows = sq.execute(
        "SELECT court_id, field_name, value, start_time, last_seen_time FROM field_state"
    ).fetchall()
    if not rows:
        return 0
    with pg_cursor(pg) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO field_state(court_id, field_name, value, start_time, last_seen_time)
            VALUES %s
            ON CONFLICT(court_id, field_name) DO UPDATE SET
              value=EXCLUDED.value,
              start_time=EXCLUDED.start_time,
              last_seen_time=EXCLUDED.last_seen_time
            """,
            [(r["court_id"], r["field_name"], r["value"], r["start_time"], r["last_seen_time"]) for r in rows],
        )
    return len(rows)


def migrate_event_trace(sq: sqlite3.Connection, pg, batch_size: int = 500) -> int:
    with pg_cursor(pg) as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM event_trace")
        max_id = cur.fetchone()["coalesce"]

    rows = sq.execute(
        """
        SELECT id, court_id, field_name, old_value, new_value,
               start_time, end_time, duration_seconds, observed_time
        FROM event_trace
        WHERE id > ?
        ORDER BY id
        """,
        (max_id,),
    ).fetchall()

    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        with pg_cursor(pg) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO event_trace(
                  court_id, field_name, old_value, new_value,
                  start_time, end_time, duration_seconds, observed_time
                ) VALUES %s
                ON CONFLICT DO NOTHING
                """,
                [
                    (r["court_id"], r["field_name"], r["old_value"], r["new_value"],
                     r["start_time"], r["end_time"], r["duration_seconds"], r["observed_time"])
                    for r in batch
                ],
            )
        total += len(batch)
        print(f"  event_trace: {total}/{len(rows)}", end="\r")

    print()
    return total


def migrate_vc_zoom_link(sq: sqlite3.Connection, pg) -> int:
    rows = sq.execute(
        "SELECT date, room_no, zoom_url, scraped_at FROM vc_zoom_link"
    ).fetchall()
    if not rows:
        return 0
    with pg_cursor(pg) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO vc_zoom_link(date, room_no, zoom_url, scraped_at)
            VALUES %s
            ON CONFLICT(date, room_no) DO UPDATE SET
              zoom_url=EXCLUDED.zoom_url,
              scraped_at=EXCLUDED.scraped_at
            """,
            [(r["date"], r["room_no"], r["zoom_url"], r["scraped_at"]) for r in rows],
        )
    return len(rows)


def migrate_subscriptions(sq: sqlite3.Connection, pg) -> int:
    rows = sq.execute("SELECT * FROM subscriptions").fetchall()
    if not rows:
        return 0
    with pg_cursor(pg) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO subscriptions(
              telegram_id, room_no, target_serial, look_ahead, active, created_at,
              hearing_date, contact_type, last_notified_serial, display_name,
              phone, alerted_at, reminder_sent
            ) VALUES %s
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    r["telegram_id"], r["room_no"], r["target_serial"], r["look_ahead"],
                    r["active"], r["created_at"], r["hearing_date"], r["contact_type"],
                    r["last_notified_serial"], r["display_name"], r["phone"],
                    r["alerted_at"], r["reminder_sent"],
                )
                for r in rows
            ],
        )
    return len(rows)


def migrate_monitor_state(sq: sqlite3.Connection, pg) -> int:
    rows = sq.execute("SELECT key, value FROM monitor_state").fetchall()
    if not rows:
        return 0
    with pg_cursor(pg) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO monitor_state(key, value) VALUES %s
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
            """,
            [(r["key"], r["value"]) for r in rows],
        )
    return len(rows)


def migrate_causelist(sq: sqlite3.Connection, pg, batch_size: int = 200) -> tuple[int, int]:
    # bench first, then cases (FK dependency)
    benches = sq.execute(
        """
        SELECT id, list_date, court_no, bench_label, side, list_type,
               judges_json, not_sitting, vc_link, jurisdiction, scraped_at
        FROM causelist_bench
        """
    ).fetchall()

    bench_id_map: dict[int, int] = {}  # sqlite_id → postgres_id

    for bench in benches:
        with pg_cursor(pg) as cur:
            cur.execute(
                """
                INSERT INTO causelist_bench(
                  list_date, court_no, bench_label, side, list_type,
                  judges_json, not_sitting, vc_link, jurisdiction, scraped_at
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(list_date, court_no) DO UPDATE SET
                  bench_label=EXCLUDED.bench_label,
                  judges_json=EXCLUDED.judges_json,
                  scraped_at=EXCLUDED.scraped_at
                RETURNING id
                """,
                (
                    bench["list_date"], bench["court_no"], bench["bench_label"],
                    bench["side"], bench["list_type"], bench["judges_json"],
                    bench["not_sitting"], bench["vc_link"], bench["jurisdiction"],
                    bench["scraped_at"],
                ),
            )
            pg_id = cur.fetchone()["id"]
        bench_id_map[bench["id"]] = pg_id

    cases = sq.execute(
        """
        SELECT bench_id, list_date, court_no, serial_no,
               case_ref, case_type, case_number, case_year,
               petitioner, respondent, advocate, pro_se,
               ia_numbers_json, section, subsection, hearing_type,
               raw_text, scraped_at
        FROM causelist_case
        """
    ).fetchall()

    total_cases = 0
    for i in range(0, len(cases), batch_size):
        batch = cases[i : i + batch_size]
        with pg_cursor(pg) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO causelist_case(
                  bench_id, list_date, court_no, serial_no,
                  case_ref, case_type, case_number, case_year,
                  petitioner, respondent, advocate, pro_se,
                  ia_numbers_json, section, subsection, hearing_type,
                  raw_text, scraped_at
                ) VALUES %s
                ON CONFLICT(bench_id, serial_no) DO NOTHING
                """,
                [
                    (
                        bench_id_map.get(r["bench_id"], r["bench_id"]),
                        r["list_date"], r["court_no"], r["serial_no"],
                        r["case_ref"], r["case_type"], r["case_number"], r["case_year"],
                        r["petitioner"], r["respondent"], r["advocate"], r["pro_se"],
                        r["ia_numbers_json"], r["section"], r["subsection"], r["hearing_type"],
                        r["raw_text"], r["scraped_at"],
                    )
                    for r in batch
                ],
            )
        total_cases += len(batch)
        print(f"  causelist_case: {total_cases}/{len(cases)}", end="\r")

    print()
    return len(benches), total_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite → Postgres")
    parser.add_argument("--sqlite", default="data/eventtrace.sqlite3", help="SQLite file path")
    parser.add_argument("--postgres", required=True, help="Postgres DSN")
    parser.add_argument("--skip-events", action="store_true", help="Skip event_trace (large)")
    args = parser.parse_args()

    print(f"Source: {args.sqlite}")
    print(f"Target: {args.postgres[:40]}...")

    sq = sqlite3.connect(args.sqlite)
    sq.row_factory = sqlite3.Row

    pg = psycopg2.connect(args.postgres)

    t0 = time.time()

    steps = [
        ("current_state", lambda: migrate_current_state(sq, pg)),
        ("field_state", lambda: migrate_field_state(sq, pg)),
        ("vc_zoom_link", lambda: migrate_vc_zoom_link(sq, pg)),
        ("subscriptions", lambda: migrate_subscriptions(sq, pg)),
        ("monitor_state", lambda: migrate_monitor_state(sq, pg)),
        ("causelist", lambda: migrate_causelist(sq, pg)),
    ]
    if not args.skip_events:
        steps.insert(2, ("event_trace", lambda: migrate_event_trace(sq, pg)))

    for name, fn in steps:
        print(f"\nMigrating {name}...")
        result = fn()
        if isinstance(result, tuple):
            print(f"  benches: {result[0]}, cases: {result[1]}")
        else:
            print(f"  rows: {result}")

    sq.close()
    pg.close()

    print(f"\nDone in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

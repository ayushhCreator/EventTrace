"""Repositories for causelist tables: causelist_bench, causelist_case, search."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ...common.time import iso, utc_now


class SQLiteCauselistRepository:
    """SQLite-backed repository for causelist_bench and causelist_case."""

    def __init__(self, connect_fn) -> None:
        self._connect = connect_fn

    def get_causelist_bench(self, list_date: str, court_no: str) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM causelist_bench WHERE list_date=? AND court_no=?",
                (list_date, court_no),
            ).fetchone()
        return dict(row) if row else None

    def list_causelist_benches(self, list_date: str) -> list[dict[str, Any]]:
        with self._connect() as con:
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
        with self._connect() as con:
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
        with self._connect() as con:
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

        with self._connect() as con:
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
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT list_date FROM causelist_bench ORDER BY list_date DESC"
            ).fetchall()
        return [r["list_date"] for r in rows]

    def list_causelist_prefixes(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT substr(case_ref, 1, instr(case_ref, '/') - 1) AS prefix
                FROM causelist_case
                WHERE case_ref LIKE '%/%'
                ORDER BY prefix
                """
            ).fetchall()
        return [r["prefix"] for r in rows if r["prefix"]]

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        now_iso = iso(scraped_at or utc_now())
        total = 0
        with self._connect() as con:
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


class PostgresCauselistRepository:
    """PostgreSQL-backed repository for causelist_bench and causelist_case."""

    def __init__(self, cursor_ctx) -> None:
        self._cursor = cursor_ctx

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

    def list_causelist_prefixes(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT split_part(case_ref, '/', 1) AS prefix
                FROM causelist_case
                WHERE case_ref LIKE '%/%'
                ORDER BY prefix
                """
            )
            return [r["prefix"] for r in cur.fetchall() if r["prefix"]]

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

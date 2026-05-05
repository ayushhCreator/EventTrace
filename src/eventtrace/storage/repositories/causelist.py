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

    def get_causelist_bench(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["list_date=?", "court_no=?"]
        params: list[Any] = [list_date, court_no]
        if side:
            clauses.append("side=?")
            params.append(side)
        if list_type:
            clauses.append("list_type=?")
            params.append(list_type)
        with self._connect() as con:
            row = con.execute(
                f"SELECT * FROM causelist_bench WHERE {' AND '.join(clauses)} LIMIT 1",
                params,
            ).fetchone()
        return dict(row) if row else None

    def list_causelist_benches(
        self,
        list_date: str,
        side: str | None = None,
        list_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["cb.list_date=?"]
        params: list[Any] = [list_date]
        if side:
            clauses.append("cb.side=?")
            params.append(side)
        if list_type:
            clauses.append("cb.list_type=?")
            params.append(list_type)
        where = " AND ".join(clauses)
        with self._connect() as con:
            rows = con.execute(
                f"""
                SELECT cb.*, COUNT(cc.id) AS case_count
                FROM causelist_bench cb
                LEFT JOIN causelist_case cc ON cc.bench_id = cb.id
                WHERE {where}
                GROUP BY cb.id
                ORDER BY cb.court_no
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def list_causelist_cases(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["cc.list_date=?", "cc.court_no=?"]
        params: list[Any] = [list_date, court_no]
        if side or list_type:
            clauses.append(
                "cc.bench_id IN (SELECT id FROM causelist_bench WHERE list_date=? AND court_no=?"
            )
            params += [list_date, court_no]
            if side:
                clauses[-1] += " AND side=?"
                params.append(side)
            if list_type:
                clauses[-1] += " AND list_type=?"
                params.append(list_type)
            clauses[-1] += ")"
        with self._connect() as con:
            rows = con.execute(
                f"SELECT * FROM causelist_case WHERE {' AND '.join(clauses)} ORDER BY serial_no",
                params,
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
        judge: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        side: str | None = None,
        list_type: str | None = None,
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
        if judge:
            clauses.append("cb.judges_json LIKE ?")
            params.append(f"%{judge.upper()}%")
        if date_from:
            clauses.append("cc.list_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("cc.list_date <= ?")
            params.append(date_to)
        if side:
            clauses.append("cb.side = ?")
            params.append(side)
        if list_type:
            clauses.append("cb.list_type = ?")
            params.append(list_type)

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

    def is_causelist_source_scraped(self, list_date: str, source_id: str) -> bool:
        with self._connect() as con:
            row = con.execute(
                "SELECT 1 FROM causelist_bench WHERE list_date=? AND source_id=? LIMIT 1",
                (list_date, source_id),
            ).fetchone()
        return row is not None

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
                source_id = bench.get("source_id")
                side = bench.get("side") or "APPELLATE SIDE"
                list_type = bench.get("list_type") or "DAILY"
                con.execute(
                    """
                    INSERT INTO causelist_bench(
                      list_date, court_no, bench_label, side, list_type,
                      judges_json, not_sitting, vc_link, jurisdiction, scraped_at, source_id
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(list_date, court_no, side, list_type) DO UPDATE SET
                      bench_label=excluded.bench_label,
                      judges_json=excluded.judges_json,
                      not_sitting=excluded.not_sitting, vc_link=excluded.vc_link,
                      jurisdiction=excluded.jurisdiction, scraped_at=excluded.scraped_at,
                      source_id=excluded.source_id
                    """,
                    (
                        bench["list_date"],
                        bench["court_no"],
                        bench.get("bench_label"),
                        side,
                        list_type,
                        judges_json,
                        not_sitting,
                        bench.get("vc_link"),
                        bench.get("jurisdiction_notes"),
                        now_iso,
                        source_id,
                    ),
                )
                row = con.execute(
                    "SELECT id FROM causelist_bench WHERE list_date=? AND court_no=? AND side=? AND list_type=?",
                    (bench["list_date"], bench["court_no"], side, list_type),
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
                            bench_id,
                            bench["list_date"],
                            bench["court_no"],
                            case["serial_no"],
                            case["case_ref"],
                            case["case_type"],
                            case["case_number"],
                            case["case_year"],
                            case.get("petitioner"),
                            case.get("respondent"),
                            case.get("advocate"),
                            1 if case.get("pro_se") else 0,
                            ia_json,
                            case.get("section"),
                            case.get("subsection"),
                            case.get("hearing_type"),
                            case.get("raw_text"),
                            now_iso,
                        ),
                    )
                    total += 1
        return total


class PostgresCauselistRepository:
    """PostgreSQL-backed repository for causelist_bench and causelist_case."""

    def __init__(self, cursor_ctx) -> None:
        self._cursor = cursor_ctx

    def get_causelist_bench(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["list_date=%s", "court_no=%s"]
        params: list[Any] = [list_date, court_no]
        if side:
            clauses.append("side=%s")
            params.append(side)
        if list_type:
            clauses.append("list_type=%s")
            params.append(list_type)
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM causelist_bench WHERE {' AND '.join(clauses)} LIMIT 1",
                params,
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def list_causelist_benches(
        self,
        list_date: str,
        side: str | None = None,
        list_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["cb.list_date=%s"]
        params: list[Any] = [list_date]
        if side:
            clauses.append("cb.side=%s")
            params.append(side)
        if list_type:
            clauses.append("cb.list_type=%s")
            params.append(list_type)
        where = " AND ".join(clauses)
        with self._cursor() as cur:
            cur.execute(
                f"""
                SELECT cb.*, COUNT(cc.id) AS case_count
                FROM causelist_bench cb
                LEFT JOIN causelist_case cc ON cc.bench_id = cb.id
                WHERE {where}
                GROUP BY cb.id
                ORDER BY cb.court_no
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def list_causelist_cases(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["cc.list_date=%s", "cc.court_no=%s"]
        params: list[Any] = [list_date, court_no]
        if side or list_type:
            sub = "SELECT id FROM causelist_bench WHERE list_date=%s AND court_no=%s"
            params += [list_date, court_no]
            if side:
                sub += " AND side=%s"
                params.append(side)
            if list_type:
                sub += " AND list_type=%s"
                params.append(list_type)
            clauses.append(f"cc.bench_id IN ({sub})")
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM causelist_case WHERE {' AND '.join(clauses)} ORDER BY serial_no",
                params,
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
        judge: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        side: str | None = None,
        list_type: str | None = None,
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
        if judge:
            clauses.append("cb.judges_json ILIKE %s")
            params.append(f"%{judge}%")
        if date_from:
            clauses.append("cc.list_date >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("cc.list_date <= %s")
            params.append(date_to)
        if side:
            clauses.append("cb.side = %s")
            params.append(side)
        if list_type:
            clauses.append("cb.list_type = %s")
            params.append(list_type)

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

    def is_causelist_source_scraped(self, list_date: str, source_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM causelist_bench WHERE list_date=%s AND source_id=%s LIMIT 1",
                (list_date, source_id),
            )
            return cur.fetchone() is not None

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
            cur.execute("SET LOCAL statement_timeout = 0")
            for court in parsed:
                bench = court["bench"]
                cases = court["cases"]
                if not bench.get("court_no") or not bench.get("list_date"):
                    continue
                judges_json = json.dumps(bench.get("judges") or [], ensure_ascii=False)
                not_sitting = 1 if bench.get("not_sitting") else 0
                source_id = bench.get("source_id")
                side = bench.get("side") or "APPELLATE SIDE"
                list_type = bench.get("list_type") or "DAILY"
                cur.execute(
                    """
                    INSERT INTO causelist_bench(
                      list_date, court_no, bench_label, side, list_type,
                      judges_json, not_sitting, vc_link, jurisdiction, scraped_at, source_id
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(list_date, court_no, side, list_type) DO UPDATE SET
                      bench_label=EXCLUDED.bench_label,
                      judges_json=EXCLUDED.judges_json,
                      not_sitting=EXCLUDED.not_sitting, vc_link=EXCLUDED.vc_link,
                      jurisdiction=EXCLUDED.jurisdiction, scraped_at=EXCLUDED.scraped_at,
                      source_id=EXCLUDED.source_id
                    RETURNING id
                    """,
                    (
                        bench["list_date"],
                        bench["court_no"],
                        bench.get("bench_label"),
                        side,
                        list_type,
                        judges_json,
                        not_sitting,
                        bench.get("vc_link"),
                        bench.get("jurisdiction_notes"),
                        now_iso,
                        source_id,
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
                            bench_id,
                            bench["list_date"],
                            bench["court_no"],
                            case["serial_no"],
                            case["case_ref"],
                            case["case_type"],
                            case["case_number"],
                            case["case_year"],
                            case.get("petitioner"),
                            case.get("respondent"),
                            case.get("advocate"),
                            1 if case.get("pro_se") else 0,
                            ia_json,
                            case.get("section"),
                            case.get("subsection"),
                            case.get("hearing_type"),
                            case.get("raw_text"),
                            now_iso,
                        ),
                    )
                    total += 1
        return total

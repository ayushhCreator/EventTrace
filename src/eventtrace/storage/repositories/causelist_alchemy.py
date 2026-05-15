"""SQLAlchemy-based causelist repository.

Single implementation for both SQLite and PostgreSQL.
Replaces SQLiteCauselistRepository + PostgresCauselistRepository.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ...common.time import iso, utc_now
from ..models import CauselistBench, CauselistCase

_SEARCH_CASE_REF_RE = re.compile(r"^([A-Za-z][A-Za-z0-9\.\(\)\-]*)[\s/]+(\d+)(?:[\s/]+(\d{4}))?$")

_NBSP = "\xa0"


def _normalize_side(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.replace(_NBSP, " ").strip()
    s = re.sub(r"\s+", " ", s)
    up = s.upper()
    if "APPELLATE" in up:
        return "APPELLATE SIDE"
    if "ORIGINAL" in up:
        return "ORIGINAL SIDE"
    return s or None


def _side_col_normalized():
    return func.upper(func.replace(CauselistBench.side, _NBSP, " "))


def _is_pg(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


# ── Canonical entity helpers ──────────────────────────────────────────────────

_DESIG_RE = re.compile(
    r"^(CHIEF\s+JUSTICE|JUSTICE|DR\.?\s+JUSTICE)",
    re.IGNORECASE,
)


def _parse_judge_raw(raw: str) -> tuple[str, str]:
    """Return (designation, normalized_name) from a raw judge string.

    Input: 'CHIEF JUSTICE SUJOY PAUL' or 'DR. JUSTICE AMRITA SINHA'
    Output: ('CHIEF_JUSTICE', 'SUJOY PAUL')
    """
    s = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip().upper()
    m = _DESIG_RE.match(s)
    if m:
        raw_desig = m.group(1)
        name = s[m.end():].strip()
        if "CHIEF" in raw_desig:
            desig = "CHIEF_JUSTICE"
        elif "DR" in raw_desig:
            desig = "DR_JUSTICE"
        else:
            desig = "JUSTICE"
    else:
        desig = "JUSTICE"
        name = s
    return desig, name


def _normalize_advocate_name(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.replace("\xa0", " ").strip().upper())
    s = re.sub(r"^(MR\.?|MRS\.?|MS\.?|DR\.?|LD\.?\s+ADV\.?|ADV\.?)\s+", "", s)
    return s.strip() or None


def _upsert_operational_rules(
    session: Any,
    bench_id: int,
    sched: dict[str, Any],
    now_iso: str,
    pg: bool,
) -> None:
    """Replace operational_rule rows for this bench from scheduling_notes_json."""
    if not pg or not sched:
        return
    session.execute(
        text("DELETE FROM operational_rule WHERE bench_id = :bid"),
        {"bid": bench_id},
    )
    rows: list[dict[str, Any]] = []

    # DAY_ORDER — one row per (bench, day)
    for day, cats in (sched.get("day_order") or {}).items():
        if cats:
            rows.append({
                "bench_id": bench_id,
                "rule_type": "DAY_ORDER",
                "day_of_week": day.lower(),
                "category_order_json": json.dumps(cats, ensure_ascii=False),
                "time_value": None,
                "raw_note": None,
                "note_index": 0,
            })

    # HEARING_TIME
    if sched.get("hearing_start_time"):
        rows.append({
            "bench_id": bench_id,
            "rule_type": "HEARING_TIME",
            "day_of_week": None,
            "category_order_json": None,
            "time_value": sched["hearing_start_time"],
            "raw_note": None,
            "note_index": 0,
        })

    # MENTIONING
    if sched.get("mentioning_allowed"):
        rows.append({
            "bench_id": bench_id,
            "rule_type": "MENTIONING",
            "day_of_week": None,
            "category_order_json": None,
            "time_value": None,
            "raw_note": None,
            "note_index": 0,
        })

    # RAW_NOTE — verbatim numbered items
    for idx, note in enumerate(sched.get("raw_notes") or []):
        if note and note.strip():
            rows.append({
                "bench_id": bench_id,
                "rule_type": "RAW_NOTE",
                "day_of_week": None,
                "category_order_json": None,
                "time_value": None,
                "raw_note": note.strip(),
                "note_index": idx,
            })

    if rows:
        session.execute(
            text("""
                INSERT INTO operational_rule
                  (bench_id, rule_type, day_of_week, category_order_json,
                   time_value, raw_note, note_index)
                VALUES
                  (:bench_id, :rule_type, :day_of_week, :category_order_json,
                   :time_value, :raw_note, :note_index)
            """),
            rows,
        )


def _upsert_judges(
    session: Any,
    bench_id: int,
    judge_names: list[str],
    court_id: str,
    now_iso: str,
    pg: bool,
) -> None:
    """Upsert judges into `judge` table; refresh bench_judge join rows."""
    if not judge_names or not pg:
        return
    # Delete stale bench_judge rows for this bench (full refresh on re-scrape)
    session.execute(
        text("DELETE FROM causelist_bench_judge WHERE bench_id = :bid"),
        {"bid": bench_id},
    )
    for order_idx, raw in enumerate(judge_names):
        desig, norm_name = _parse_judge_raw(raw)
        if not norm_name:
            continue
        row = session.execute(
            text("""
                INSERT INTO judge(court_id, normalized_name, full_name, designation,
                                  first_seen_at, last_seen_at, active)
                VALUES(:court_id, :norm, :full, :desig, :now, :now, 1)
                ON CONFLICT(court_id, normalized_name) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    active = 1
                RETURNING id
            """),
            {
                "court_id": court_id,
                "norm": norm_name,
                "full": raw.strip().upper(),
                "desig": desig,
                "now": now_iso,
            },
        ).fetchone()
        if row:
            session.execute(
                text("""
                    INSERT INTO causelist_bench_judge(bench_id, judge_id, order_index)
                    VALUES(:bid, :jid, :oidx)
                    ON CONFLICT(bench_id, judge_id) DO UPDATE SET order_index = excluded.order_index
                """),
                {"bid": bench_id, "jid": row[0], "oidx": order_idx},
            )


def _upsert_advocate(
    session: Any,
    case_id: int,
    advocate_raw: str | None,
    role: str,
    now_iso: str,
    pg: bool,
) -> None:
    """Upsert single advocate into `advocate` table; link to case."""
    if not advocate_raw or not pg:
        return
    norm = _normalize_advocate_name(advocate_raw)
    if not norm:
        return
    row = session.execute(
        text("""
            INSERT INTO advocate(normalized_name, display_name, first_seen_at, last_seen_at)
            VALUES(:norm, :disp, :now, :now)
            ON CONFLICT(normalized_name) DO UPDATE SET last_seen_at = excluded.last_seen_at
            RETURNING id
        """),
        {"norm": norm, "disp": advocate_raw.strip().upper(), "now": now_iso},
    ).fetchone()
    if row:
        session.execute(
            text("""
                INSERT INTO causelist_case_advocate(case_id, advocate_id, role)
                VALUES(:cid, :aid, :role)
                ON CONFLICT(case_id, advocate_id, role) DO NOTHING
            """),
            {"cid": case_id, "aid": row[0], "role": role},
        )


class SQLAlchemyCauselistRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_causelist_bench(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any] | None:
        side_norm = _normalize_side(side)
        with Session(self._engine) as session:
            q = select(CauselistBench).where(
                CauselistBench.list_date == list_date, CauselistBench.court_no == court_no
            )
            if side_norm:
                q = q.where(_side_col_normalized() == side_norm.upper())
            if list_type:
                q = q.where(CauselistBench.list_type == list_type)
            if source_id:
                q = q.where(CauselistBench.source_id == source_id)
            obj = session.scalar(q.limit(1))
        return _bench_to_dict(obj) if obj else None

    def list_causelist_benches(
        self,
        list_date: str,
        side: str | None = None,
        list_type: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        side_norm = _normalize_side(side)
        with Session(self._engine) as session:
            q = (
                select(
                    *CauselistBench.__table__.columns,
                    func.count(CauselistCase.id).label("case_count"),
                )
                .outerjoin(CauselistCase, CauselistCase.bench_id == CauselistBench.id)
                .where(CauselistBench.list_date == list_date)
                .group_by(CauselistBench.id)
                .order_by(
                    text("CASE WHEN causelist_bench.court_no ~ '^[0-9]+$' THEN causelist_bench.court_no::integer ELSE 9999 END"),
                    CauselistBench.at_time,
                )
            )
            if side_norm:
                q = q.where(_side_col_normalized() == side_norm.upper())
            if list_type:
                q = q.where(CauselistBench.list_type == list_type)
            if source_id:
                q = q.where(CauselistBench.source_id == source_id)
            rows = session.execute(q).mappings().all()
        return [dict(r) for r in rows]

    def list_causelist_cases(
        self,
        list_date: str,
        court_no: str,
        side: str | None = None,
        list_type: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        side_norm = _normalize_side(side)
        with Session(self._engine) as session:
            q = (
                select(CauselistCase)
                .where(CauselistCase.list_date == list_date, CauselistCase.court_no == court_no)
                .order_by(CauselistCase.serial_no)
            )
            if side_norm or list_type or source_id:
                sub = select(CauselistBench.id).where(
                    CauselistBench.list_date == list_date, CauselistBench.court_no == court_no
                )
                if side_norm:
                    sub = sub.where(_side_col_normalized() == side_norm.upper())
                if list_type:
                    sub = sub.where(CauselistBench.list_type == list_type)
                if source_id:
                    sub = sub.where(CauselistBench.source_id == source_id)
                q = q.where(CauselistCase.bench_id.in_(sub))
            rows = session.scalars(q).all()
        return [_case_to_dict(r) for r in rows]

    def get_bench_by_id(self, bench_id: int) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            row = session.get(CauselistBench, bench_id)
            return _bench_to_dict(row) if row else None

    def list_cases_by_bench_id(self, bench_id: int) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            q = (
                select(CauselistCase)
                .where(CauselistCase.bench_id == bench_id)
                .order_by(CauselistCase.serial_no)
            )
            return [_case_to_dict(r) for r in session.scalars(q)]

    def get_causelist_case_by_serial(
        self, list_date: str, court_no: str, serial_no: int
    ) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            q = (
                select(
                    *CauselistCase.__table__.columns,
                    CauselistBench.judges_json,
                    CauselistBench.vc_link,
                    CauselistBench.bench_label,
                )
                .join(CauselistBench, CauselistBench.id == CauselistCase.bench_id)
                .where(
                    CauselistCase.list_date == list_date,
                    CauselistCase.court_no == court_no,
                    CauselistCase.serial_no == serial_no,
                )
            )
            row = session.execute(q).mappings().first()
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
        section: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            q = (
                select(
                    *CauselistCase.__table__.columns,
                    CauselistBench.judges_json,
                    CauselistBench.vc_link,
                    CauselistBench.bench_label,
                    CauselistBench.jurisdiction,
                    CauselistBench.side,
                )
                .join(CauselistBench, CauselistBench.id == CauselistCase.bench_id)
                .order_by(
                    CauselistCase.list_date.desc(), CauselistCase.court_no, CauselistCase.serial_no
                )
                .limit(limit)
            )

            if case_ref:
                m = _SEARCH_CASE_REF_RE.match(case_ref.strip())
                if m:
                    type_prefix = m.group(1).upper()
                    num = m.group(2).lstrip("0") or m.group(2)
                    year = m.group(3)
                    q = q.where(CauselistCase.case_type.ilike(f"{type_prefix}%"))
                    q = q.where(CauselistCase.case_number == num)
                    if year:
                        q = q.where(CauselistCase.case_year == int(year))
                else:
                    q = q.where(CauselistCase.case_ref.ilike(f"%{case_ref}%"))

            if advocate:
                q = q.where(CauselistCase.advocate.ilike(f"%{advocate}%"))
            if party:
                q = q.where(
                    CauselistCase.petitioner.ilike(f"%{party}%")
                    | CauselistCase.respondent.ilike(f"%{party}%")
                )
            if judge:
                q = q.where(CauselistBench.judges_json.ilike(f"%{judge}%"))
            if date_from:
                q = q.where(CauselistCase.list_date >= date_from)
            if date_to:
                q = q.where(CauselistCase.list_date <= date_to)
            if side:
                q = q.where(CauselistBench.side == side)
            if list_type:
                q = q.where(CauselistBench.list_type == list_type)
            if section:
                q = q.where(CauselistCase.section.ilike(f"%{section}%"))

            rows = session.execute(q).mappings().all()
        return [dict(r) for r in rows]

    def list_causelist_dates(self) -> list[str]:
        with Session(self._engine) as session:
            rows = (
                session.execute(
                    select(CauselistBench.list_date)
                    .distinct()
                    .order_by(CauselistBench.list_date.desc())
                )
                .scalars()
                .all()
            )
        return list(rows)

    def is_causelist_source_scraped(self, list_date: str, source_id: str) -> bool:
        with Session(self._engine) as session:
            row = session.scalar(
                select(CauselistBench)
                .where(CauselistBench.list_date == list_date, CauselistBench.source_id == source_id)
                .limit(1)
            )
        return row is not None

    def list_causelist_prefixes(self) -> list[str]:
        with Session(self._engine) as session:
            if _is_pg(self._engine):
                rows = session.execute(
                    text(
                        "SELECT DISTINCT split_part(case_ref, '/', 1) AS prefix "
                        "FROM causelist_case WHERE case_ref LIKE '%/%' ORDER BY prefix"
                    )
                ).all()
            else:
                rows = session.execute(
                    text(
                        "SELECT DISTINCT substr(case_ref, 1, instr(case_ref, '/') - 1) AS prefix "
                        "FROM causelist_case WHERE case_ref LIKE '%/%' ORDER BY prefix"
                    )
                ).all()
        return [r.prefix for r in rows if r.prefix]

    def list_available_list_types(self, list_date: str) -> list[dict[str, Any]]:
        """Return which (side, list_type) combos have data for a date, with bench count."""
        with Session(self._engine) as session:
            rows = session.execute(
                text("""
                    SELECT side, list_type, COUNT(*) AS bench_count
                    FROM causelist_bench
                    WHERE list_date = :date
                    GROUP BY side, list_type
                    ORDER BY side, list_type
                """),
                {"date": list_date},
            ).fetchall()
        return [{"side": r.side, "list_type": r.list_type, "bench_count": r.bench_count} for r in rows]

    def list_bench_rules(self, bench_id: int) -> list[dict[str, Any]]:
        """Return operational_rule rows for a bench, ordered by type then note_index."""
        with Session(self._engine) as session:
            rows = session.execute(
                text("""
                    SELECT rule_type, day_of_week, category_order_json,
                           time_value, raw_note, note_index
                    FROM operational_rule
                    WHERE bench_id = :bid
                    ORDER BY rule_type, note_index
                """),
                {"bid": bench_id},
            ).fetchall()
        return [
            {
                "rule_type": r.rule_type,
                "day_of_week": r.day_of_week,
                "category_order_json": r.category_order_json,
                "time_value": r.time_value,
                "raw_note": r.raw_note,
                "note_index": r.note_index,
            }
            for r in rows
        ]

    def list_judges_for_date(
        self, list_date: str, side: str | None = None
    ) -> list[dict[str, Any]]:
        """Return distinct judges sitting on a date, with bench count per judge."""
        with Session(self._engine) as session:
            where = "WHERE cb.list_date = :date"
            params: dict[str, Any] = {"date": list_date}
            if side:
                where += " AND cb.side = :side"
                params["side"] = side
            rows = session.execute(
                text(f"""
                    SELECT j.id, j.normalized_name, j.full_name, j.designation,
                           COUNT(DISTINCT cbj.bench_id) AS bench_count
                    FROM judge j
                    JOIN causelist_bench_judge cbj ON cbj.judge_id = j.id
                    JOIN causelist_bench cb ON cb.id = cbj.bench_id
                    {where}
                    GROUP BY j.id, j.normalized_name, j.full_name, j.designation
                    ORDER BY j.normalized_name
                """),
                params,
            ).fetchall()
        return [
            {
                "id": r.id,
                "normalized_name": r.normalized_name,
                "full_name": r.full_name,
                "designation": r.designation,
                "bench_count": r.bench_count,
            }
            for r in rows
        ]

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        now_iso = iso(scraped_at or utc_now())
        total = 0
        pg = _is_pg(self._engine)
        with Session(self._engine) as session:
            if pg:
                session.execute(text("SET LOCAL statement_timeout = 0"))
            for court in parsed:
                bench = court["bench"]
                cases = court["cases"]
                if not bench.get("court_no") or not bench.get("list_date"):
                    continue
                judges_json = json.dumps(bench.get("judges") or [], ensure_ascii=False)
                not_sitting = 1 if bench.get("not_sitting") else 0
                source_id = bench.get("source_id")
                side = _normalize_side(bench.get("side")) or "APPELLATE SIDE"
                list_type = bench.get("list_type") or "DAILY"
                at_time = bench.get("at_time") or ""
                # Normalise bench_label: strip trailing space before ')' so
                # 'DIVISION BENCH (DB )' and 'DIVISION BENCH (DB)' are the same key.
                bench_label = re.sub(r"\s+\)", ")", bench.get("bench_label") or "").strip()

                sched = bench.get("scheduling_notes_json") or {}
                sched_json = json.dumps(sched, ensure_ascii=False) if sched else None
                jur_groups = bench.get("jurisdiction_groups") or []
                jur_groups_json = json.dumps(jur_groups, ensure_ascii=False) if jur_groups else None

                bench_id = session.execute(
                    text("""
                    INSERT INTO causelist_bench(
                      list_date, court_no, bench_label, side, list_type,
                      judges_json, not_sitting, vc_link, jurisdiction, scraped_at, source_id,
                      at_time, floor, building, source_court,
                      scheduling_notes_json, hearing_start_time, mentioning_allowed,
                      jurisdiction_groups_json
                    ) VALUES(
                      :list_date, :court_no, :bench_label, :side, :list_type,
                      :judges_json, :not_sitting, :vc_link, :jurisdiction, :scraped_at, :source_id,
                      :at_time, :floor, :building, :source_court,
                      :scheduling_notes_json, :hearing_start_time, :mentioning_allowed,
                      :jurisdiction_groups_json
                    )
                    ON CONFLICT(list_date, court_no, side, list_type, at_time, bench_label) DO UPDATE SET
                      bench_label=excluded.bench_label,
                      judges_json=excluded.judges_json,
                      not_sitting=excluded.not_sitting,
                      vc_link=excluded.vc_link,
                      jurisdiction=excluded.jurisdiction,
                      scraped_at=excluded.scraped_at,
                      source_id=excluded.source_id,
                      at_time=excluded.at_time,
                      floor=excluded.floor,
                      building=excluded.building,
                      source_court=excluded.source_court,
                      scheduling_notes_json=excluded.scheduling_notes_json,
                      hearing_start_time=excluded.hearing_start_time,
                      mentioning_allowed=excluded.mentioning_allowed,
                      jurisdiction_groups_json=excluded.jurisdiction_groups_json
                    RETURNING id
                """),
                    {
                        "list_date": bench["list_date"],
                        "court_no": bench["court_no"],
                        "bench_label": bench_label,
                        "side": side,
                        "list_type": list_type,
                        "judges_json": judges_json,
                        "not_sitting": not_sitting,
                        "vc_link": bench.get("vc_link"),
                        "jurisdiction": bench.get("jurisdiction_notes"),
                        "scraped_at": now_iso,
                        "source_id": source_id,
                        "at_time": at_time,
                        "floor": bench.get("floor"),
                        "building": bench.get("building"),
                        "source_court": bench.get("source_court") or "CHD",
                        "scheduling_notes_json": sched_json,
                        "hearing_start_time": bench.get("hearing_start_time"),
                        "mentioning_allowed": 1 if bench.get("mentioning_allowed") else 0,
                        "jurisdiction_groups_json": jur_groups_json,
                    },
                ).scalar()

                # Upsert canonical judges + bench↔judge join
                _upsert_judges(
                    session,
                    bench_id,
                    bench.get("judges") or [],
                    bench.get("source_court") or "CHD",
                    now_iso,
                    pg,
                )

                # Upsert operational rules from NOTE: block
                _upsert_operational_rules(
                    session,
                    bench_id,
                    bench.get("scheduling_notes_json") or {},
                    now_iso,
                    pg,
                )

                # Delete stale cases per (section, serial_no) so that if a bench
                # shrinks within a section, orphaned rows don't accumulate.
                if cases:
                    section_max: dict[str, int] = defaultdict(int)
                    for c in cases:
                        if c.get("serial_no"):
                            sec = c.get("section") or ""
                            section_max[sec] = max(section_max[sec], c["serial_no"])
                    for sec, max_sn in section_max.items():
                        session.execute(
                            text(
                                "DELETE FROM causelist_case "
                                "WHERE bench_id=:bid AND COALESCE(section,'')=:sec AND serial_no > :max_sn"
                            ),
                            {"bid": bench_id, "sec": sec, "max_sn": max_sn},
                        )

                for case in cases:
                    ia_json = json.dumps(case.get("ia_numbers") or [], ensure_ascii=False)
                    case_result = session.execute(
                        text("""
                        INSERT INTO causelist_case(
                          bench_id, list_date, court_no, serial_no,
                          case_ref, case_type, case_number, case_year,
                          petitioner, respondent, advocate, pro_se,
                          ia_numbers_json, section, subsection, hearing_type,
                          scraped_at,
                          canonical_section, group_no,
                          case_time_annotation, is_part_heard, next_date_annotation,
                          is_with_case, parent_serial_no
                        ) VALUES(
                          :bench_id, :list_date, :court_no, :serial_no,
                          :case_ref, :case_type, :case_number, :case_year,
                          :petitioner, :respondent, :advocate, :pro_se,
                          :ia_numbers_json, :section, :subsection, :hearing_type,
                          :scraped_at,
                          :canonical_section, :group_no,
                          :case_time_annotation, :is_part_heard, :next_date_annotation,
                          :is_with_case, :parent_serial_no
                        )
                        ON CONFLICT(bench_id, COALESCE(section, ''), serial_no) DO UPDATE SET
                          case_ref=excluded.case_ref,
                          case_type=excluded.case_type,
                          case_number=excluded.case_number,
                          case_year=excluded.case_year,
                          petitioner=excluded.petitioner,
                          respondent=excluded.respondent,
                          advocate=excluded.advocate,
                          pro_se=excluded.pro_se,
                          ia_numbers_json=excluded.ia_numbers_json,
                          section=excluded.section,
                          subsection=excluded.subsection,
                          hearing_type=excluded.hearing_type,
                          scraped_at=excluded.scraped_at,
                          canonical_section=excluded.canonical_section,
                          group_no=excluded.group_no,
                          case_time_annotation=excluded.case_time_annotation,
                          is_part_heard=excluded.is_part_heard,
                          next_date_annotation=excluded.next_date_annotation,
                          is_with_case=excluded.is_with_case,
                          parent_serial_no=excluded.parent_serial_no
                    RETURNING id
                    """),
                        {
                            "bench_id": bench_id,
                            "list_date": bench["list_date"],
                            "court_no": bench["court_no"],
                            "serial_no": case["serial_no"],
                            "case_ref": case["case_ref"],
                            "case_type": case["case_type"],
                            "case_number": case["case_number"],
                            "case_year": case["case_year"],
                            "petitioner": case.get("petitioner"),
                            "respondent": case.get("respondent"),
                            "advocate": case.get("advocate"),
                            "pro_se": 1 if case.get("pro_se") else 0,
                            "ia_numbers_json": ia_json,
                            "section": case.get("section"),
                            "subsection": case.get("subsection"),
                            "hearing_type": case.get("hearing_type"),
                            "scraped_at": now_iso,
                            "canonical_section": case.get("canonical_section"),
                            "group_no": case.get("group_no"),
                            "case_time_annotation": case.get("case_time_annotation"),
                            "is_part_heard": 1 if case.get("is_part_heard") else 0,
                            "next_date_annotation": case.get("next_date_annotation"),
                            "is_with_case": 1 if case.get("is_with_case") else 0,
                            "parent_serial_no": case.get("parent_serial_no"),
                        },
                    )
                    if pg:
                        case_id_row = case_result.fetchone()
                        if case_id_row:
                            _upsert_advocate(
                                session,
                                case_id_row[0],
                                case.get("advocate"),
                                "PETITIONER",
                                now_iso,
                                pg,
                            )
                    total += 1
            session.commit()
        return total


def _bench_to_dict(r: CauselistBench) -> dict:
    return {
        "id": r.id,
        "list_date": r.list_date,
        "court_no": r.court_no,
        "bench_label": r.bench_label,
        "side": r.side,
        "list_type": r.list_type,
        "judges_json": r.judges_json,
        "not_sitting": r.not_sitting,
        "vc_link": r.vc_link,
        "jurisdiction": r.jurisdiction,
        "scraped_at": r.scraped_at,
        "source_id": r.source_id,
        "at_time": r.at_time,
        "floor": r.floor,
        "building": r.building,
        "scheduling_notes_json": r.scheduling_notes_json,
        "hearing_start_time": r.hearing_start_time,
        "mentioning_allowed": r.mentioning_allowed,
        "jurisdiction_groups_json": r.jurisdiction_groups_json,
    }


def _case_to_dict(r: CauselistCase) -> dict:
    return {
        "id": r.id,
        "bench_id": r.bench_id,
        "list_date": r.list_date,
        "court_no": r.court_no,
        "serial_no": r.serial_no,
        "case_ref": r.case_ref,
        "case_type": r.case_type,
        "case_number": r.case_number,
        "case_year": r.case_year,
        "petitioner": r.petitioner,
        "respondent": r.respondent,
        "advocate": r.advocate,
        "pro_se": r.pro_se,
        "ia_numbers_json": r.ia_numbers_json,
        "section": r.section,
        "subsection": r.subsection,
        "hearing_type": r.hearing_type,
        "scraped_at": r.scraped_at,
        "canonical_section": r.canonical_section,
        "group_no": r.group_no,
        "case_time_annotation": r.case_time_annotation,
        "is_part_heard": r.is_part_heard,
        "next_date_annotation": r.next_date_annotation,
        "is_with_case": r.is_with_case,
        "parent_serial_no": r.parent_serial_no,
    }

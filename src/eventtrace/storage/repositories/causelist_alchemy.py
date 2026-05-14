"""SQLAlchemy-based causelist repository.

Single implementation for both SQLite and PostgreSQL.
Replaces SQLiteCauselistRepository + PostgresCauselistRepository.
"""

from __future__ import annotations

import json
import re
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
                .order_by(CauselistBench.court_no)
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

    def store_causelist(
        self, parsed: list[dict[str, Any]], scraped_at: datetime | None = None
    ) -> int:
        now_iso = iso(scraped_at or utc_now())
        total = 0
        with Session(self._engine) as session:
            if _is_pg(self._engine):
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
                    ON CONFLICT(list_date, court_no, side, list_type) DO UPDATE SET
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
                        "bench_label": bench.get("bench_label"),
                        "side": side,
                        "list_type": list_type,
                        "judges_json": judges_json,
                        "not_sitting": not_sitting,
                        "vc_link": bench.get("vc_link"),
                        "jurisdiction": bench.get("jurisdiction_notes"),
                        "scraped_at": now_iso,
                        "source_id": source_id,
                        "at_time": bench.get("at_time"),
                        "floor": bench.get("floor"),
                        "building": bench.get("building"),
                        "source_court": bench.get("source_court") or "CHD",
                        "scheduling_notes_json": sched_json,
                        "hearing_start_time": bench.get("hearing_start_time"),
                        "mentioning_allowed": 1 if bench.get("mentioning_allowed") else 0,
                        "jurisdiction_groups_json": jur_groups_json,
                    },
                ).scalar()

                for case in cases:
                    ia_json = json.dumps(case.get("ia_numbers") or [], ensure_ascii=False)
                    session.execute(
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
                        ON CONFLICT(bench_id, serial_no) DO UPDATE SET
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

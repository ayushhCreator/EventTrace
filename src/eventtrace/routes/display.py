from __future__ import annotations

from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from ..common.time import IST, iso, parse_iso
from ..services.deps import get_db
from .utils import today_ist

router = APIRouter()


def _hearing_modified_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        cleaned = " ".join(value.replace("\u00a0", " ").split())
        dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        return None
    return iso(dt)


def _min_iso(a: str | None, b: str | None) -> str | None:
    if a and b:
        return a if parse_iso(a) <= parse_iso(b) else b
    return a or b


def _side_key(value: str | None) -> str:
    if not value:
        return ""
    v = value.upper()
    if "ORIGINAL" in v:
        return "O"
    if "APPELLATE" in v:
        return "A"
    return ""


def _parse_serials(value: str | None) -> list[int]:
    if not value:
        return []
    parts = [p.strip() for p in value.split(",") if p.strip()]
    nums: list[int] = []
    for part in parts:
        if "-" in part:
            start_s, end_s = [p.strip() for p in part.split("-", 1)]
            if not start_s or not end_s:
                continue
            try:
                start = int(start_s)
                end = int(end_s)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            nums.extend(range(start, end + 1))
        else:
            try:
                nums.append(int(part))
            except ValueError:
                continue
    return sorted(set(nums))


def _case_refs_for_serials(
    db: Any,
    list_date: str,
    court_no: str,
    side: str | None,
    list_type: str | None,
    serials: list[int],
) -> list[str]:
    if not serials:
        return []
    cases = db.list_causelist_cases(list_date, court_no, side=side, list_type=list_type)
    wanted = set(serials)
    seen: set[str] = set()
    ordered: list[str] = []
    for case in cases:
        if case.get("serial_no") not in wanted:
            continue
        case_ref = case.get("case_ref") or ""
        if not case_ref or case_ref in seen:
            continue
        seen.add(case_ref)
        ordered.append(case_ref)
    return ordered


@router.get("/board-status")
def board_status(db: Any = Depends(get_db)) -> dict:
    """Public endpoint: tells the UI whether the court is in session."""
    court_session = db.get_monitor_state("court_session") or "unknown"
    last_poll = db.get_monitor_state("last_successful_poll")
    board_active = db.get_monitor_state("board_active")
    return {
        "court_session": court_session,   # "open" | "closed" | "unknown"
        "last_successful_poll": last_poll,
        "board_active": board_active == "1",
    }


@router.get("/current-state")
def current_state(db: Any = Depends(get_db)) -> list[dict]:
    return db.list_current_state()


@router.get("/vc-links")
def vc_links(
    date: str | None = Query(None, description="YYYY-MM-DD IST, defaults to today"),
    db: Any = Depends(get_db),
) -> dict[str, str]:
    return db.get_vc_zoom_links(date or today_ist())


@router.get("/vc-links/dates")
def vc_link_dates(db: Any = Depends(get_db)) -> list[str]:
    return db.list_vc_dates()


@router.get("/changes")
@router.get("/event-traces")
def event_traces(
    limit: int = Query(200, ge=1, le=2000),
    court_id: str | None = None,
    db: Any = Depends(get_db),
) -> list[dict]:
    return db.list_event_traces(limit=limit, court_id=court_id)


@router.get("/field-state/{court_id}")
def field_state(court_id: str, db: Any = Depends(get_db)) -> list[dict]:
    return db.list_field_state(court_id)


@router.get("/absent-courts")
def absent_courts(db: Any = Depends(get_db)) -> list[str]:
    return db.list_absent_court_ids()


@router.get("/field-durations")
def field_durations(db: Any = Depends(get_db)) -> dict[str, str]:
    return db.list_serial_start_times()


@router.get("/display-board")
def display_board(
    date: str | None = Query(None, description="YYYY-MM-DD IST, defaults to today"),
    db: Any = Depends(get_db),
) -> list[dict]:
    import json

    target = date or today_ist()

    benches = db.list_causelist_benches(target)

    live_states = db.list_current_state()
    live: dict[tuple[str, str], dict] = {}
    live_by_room: dict[str, dict] = {}
    for s in live_states:
        data = s.get("data", {})
        room = str(data.get("room_no") or s.get("court_id") or "")
        if room:
            side_key = _side_key(data.get("side") or data.get("side_short_form"))
            entry = {
                "data": data,
                "court_id": str(s.get("court_id") or room),
                "last_seen": s.get("last_seen_time"),
            }
            if side_key:
                live[(room, side_key)] = entry
            live_by_room.setdefault(room, entry)

    absent = set(db.list_absent_court_ids())
    serial_starts = db.list_serial_start_times()
    vc_links = db.get_vc_zoom_links(target)

    results = []
    seen = set()
    used_live: set[tuple[str, str]] = set()

    for bench in benches:
        court_no = str(bench["court_no"])
        seen.add(court_no)

        side_key = _side_key(bench.get("side"))
        live_entry = live.get((court_no, side_key)) or {}
        if live_entry:
            used_live.add((court_no, side_key))
        elif not side_key and court_no in live_by_room and (court_no, "") not in used_live:
            live_entry = live_by_room[court_no]
            used_live.add((court_no, ""))
        live_data = live_entry.get("data", {})
        court_id = live_entry.get("court_id", court_no)

        try:
            judges = json.loads(bench.get("judges_json") or "[]")
        except Exception:
            judges = []

        if bench.get("not_sitting"):
            status = "NOT_SITTING"
        elif court_id in absent or court_no in absent:
            status = "DONE"
        elif live_entry:
            status = "LIVE"
        else:
            status = "WAITING"

        serial_start = serial_starts.get(court_id) or serial_starts.get(court_no)
        hearing_start = _hearing_modified_iso(live_data.get("hearing_last_modified"))
        serials = _parse_serials(live_data.get("cause_list_sr_no"))
        case_list = _case_refs_for_serials(
            db,
            target,
            court_no,
            bench.get("side"),
            bench.get("list_type"),
            serials,
        )

        results.append(
            {
                "court_no": court_no,
                "side": bench.get("side", "APPELLATE SIDE"),
                "list_type": bench.get("list_type", "DAILY"),
                "judges": judges,
                "bench_label": bench.get("bench_label"),
                "not_sitting": bool(bench.get("not_sitting")),
                "vc_link": vc_links.get(court_no) or bench.get("vc_link"),
                "at_time": bench.get("at_time"),
                "floor": bench.get("floor"),
                "building": bench.get("building"),
                "commercial": live_data.get("commercial") == "C",
                "status": status,
                "serial_no": live_data.get("cause_list_sr_no"),
                "case_no": live_data.get("case_no_string"),
                "case_list": case_list,
                "message": live_data.get("message"),
                "pass_over": live_data.get("pass_over"),
                "hearing_last_modified": live_data.get("hearing_last_modified"),
                "duration_start": _min_iso(serial_start, hearing_start),
                "last_seen_time": live_entry.get("last_seen"),
                "court_id": court_id,
            }
        )

    # Courts in live but not in cause list (cause list not yet scraped for today)
    for (room_no, side_key), live_entry in live.items():
        if (room_no, side_key) in used_live:
            continue
        if room_no in seen:
            continue
        live_data = live_entry.get("data", {})
        if live_data.get("hearing_date") and live_data["hearing_date"] != target:
            continue
        court_id = live_entry.get("court_id", room_no)
        serial_start = serial_starts.get(court_id) or serial_starts.get(room_no)
        hearing_start = _hearing_modified_iso(live_data.get("hearing_last_modified"))
        serials = _parse_serials(live_data.get("cause_list_sr_no"))
        case_list = _case_refs_for_serials(
            db,
            target,
            room_no,
            live_data.get("side"),
            live_data.get("cause_list_type_name"),
            serials,
        )

        results.append(
            {
                "court_no": room_no,
                "side": live_data.get("side", ""),
                "list_type": live_data.get("cause_list_type_name", "DAILY"),
                "judges": [live_data["judge_names"]] if live_data.get("judge_names") else [],
                "bench_label": None,
                "not_sitting": False,
                "vc_link": vc_links.get(room_no) or live_data.get("vc_link"),
                "at_time": None,
                "floor": None,
                "building": None,
                "commercial": live_data.get("commercial") == "C",
                "status": "DONE" if court_id in absent else "LIVE",
                "serial_no": live_data.get("cause_list_sr_no"),
                "case_no": live_data.get("case_no_string"),
                "case_list": case_list,
                "message": live_data.get("message"),
                "pass_over": live_data.get("pass_over"),
                "hearing_last_modified": live_data.get("hearing_last_modified"),
                "duration_start": _min_iso(serial_start, hearing_start),
                "last_seen_time": live_entry.get("last_seen"),
                "court_id": court_id,
            }
        )

    def _sort_key(x: dict) -> int:
        try:
            return int(x["court_no"])
        except (ValueError, TypeError):
            return 9999

    def _side_rank(side: str | None) -> int:
        k = _side_key(side)
        if k == "A":
            return 0
        if k == "O":
            return 1
        return 2

    # De-dupe identical LIVE rows (same court/serial/case) across sides.
    deduped: list[dict] = []
    index_by_key: dict[tuple[str, str, str], int] = {}
    for row in results:
        case_no = row.get("case_no") or ""
        serial_no = row.get("serial_no") or ""
        if row.get("status") == "LIVE" and case_no and serial_no:
            key = (str(row.get("court_no")), str(serial_no), str(case_no))
            if key in index_by_key:
                idx = index_by_key[key]
                cur = deduped[idx]
                if _side_rank(row.get("side")) < _side_rank(cur.get("side")):
                    deduped[idx] = row
                continue
            index_by_key[key] = len(deduped)
        deduped.append(row)

    deduped.sort(key=_sort_key)
    return deduped

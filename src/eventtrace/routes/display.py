from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..services.deps import get_db
from .utils import today_ist

router = APIRouter()


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
    live: dict[str, dict] = {}
    for s in live_states:
        data = s.get("data", {})
        room = str(data.get("room_no") or s.get("court_id") or "")
        if room:
            live[room] = {
                "data": data,
                "court_id": str(s.get("court_id") or room),
                "last_seen": s.get("last_seen_time"),
            }

    absent = set(db.list_absent_court_ids())
    serial_starts = db.list_serial_start_times()
    vc_links = db.get_vc_zoom_links(target)

    results = []
    seen = set()

    for bench in benches:
        court_no = str(bench["court_no"])
        seen.add(court_no)

        live_entry = live.get(court_no, {})
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
        elif court_no in live:
            status = "LIVE"
        else:
            status = "WAITING"

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
                "message": live_data.get("message"),
                "pass_over": live_data.get("pass_over"),
                "hearing_last_modified": live_data.get("hearing_last_modified"),
                "duration_start": serial_starts.get(court_id) or serial_starts.get(court_no),
                "court_id": court_id,
            }
        )

    # Courts in live but not in cause list (cause list not yet scraped for today)
    for room_no, live_entry in live.items():
        if room_no in seen:
            continue
        live_data = live_entry.get("data", {})
        if live_data.get("hearing_date") and live_data["hearing_date"] != target:
            continue
        court_id = live_entry.get("court_id", room_no)
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
                "message": live_data.get("message"),
                "pass_over": live_data.get("pass_over"),
                "hearing_last_modified": live_data.get("hearing_last_modified"),
                "duration_start": serial_starts.get(court_id) or serial_starts.get(room_no),
                "court_id": court_id,
            }
        )

    def _sort_key(x: dict) -> int:
        try:
            return int(x["court_no"])
        except (ValueError, TypeError):
            return 9999

    results.sort(key=_sort_key)
    return results

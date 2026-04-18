from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .db import DB, EventTrace, parse_iso, utc_now


PRESENT_FIELD = "__present__"


def _values_equal(a: str | None, b: str | None) -> bool:
    return (a or None) == (b or None)


def apply_snapshot(
    db: DB,
    snapshot_by_court: dict[str, dict[str, Any]],
    observed_time: datetime | None = None,
    ignore_fields: Iterable[str] = (),
) -> list[EventTrace]:
    observed_time = observed_time or utc_now()
    ignore = set(ignore_fields)

    changes: list[EventTrace] = []

    # Presence detection
    snapshot_courts = set(snapshot_by_court.keys())
    previously_known = db.known_courts()
    all_courts = snapshot_courts | previously_known

    for court_id in all_courts:
        is_present = court_id in snapshot_courts
        new_present_value = "1" if is_present else "0"

        old = db.get_field_state(court_id, PRESENT_FIELD)
        if old is None:
            db.upsert_field_state(
                court_id=court_id,
                field_name=PRESENT_FIELD,
                value=new_present_value,
                start_time=observed_time,
                last_seen_time=observed_time,
            )
        else:
            old_value = old["value"]
            if not _values_equal(old_value, new_present_value):
                trace = EventTrace(
                    court_id=court_id,
                    field_name=PRESENT_FIELD,
                    old_value=old_value,
                    new_value=new_present_value,
                    start_time=parse_iso(old["start_time"]),
                    end_time=observed_time,
                )
                db.insert_event_trace(trace, observed_time=observed_time)
                db.upsert_field_state(
                    court_id=court_id,
                    field_name=PRESENT_FIELD,
                    value=new_present_value,
                    start_time=observed_time,
                    last_seen_time=observed_time,
                )
                changes.append(trace)
            else:
                db.touch_field_state(court_id, PRESENT_FIELD, last_seen_time=observed_time)

    # Field-level detection for present courts
    for court_id, row in snapshot_by_court.items():
        db.upsert_current_state(court_id=court_id, row=row, seen_time=observed_time)

        fields_in_row = set(row.keys())
        known_fields = db.list_field_names(court_id)
        all_fields = (fields_in_row | known_fields) - set(ignore) - {"court_id", PRESENT_FIELD}

        for field in sorted(all_fields):
            if field in ignore:
                continue
            new_value = row.get(field) if field in fields_in_row else None
            if new_value is not None:
                new_value = str(new_value)

            old = db.get_field_state(court_id, field)
            if old is None:
                db.upsert_field_state(
                    court_id=court_id,
                    field_name=field,
                    value=new_value,
                    start_time=observed_time,
                    last_seen_time=observed_time,
                )
                continue

            old_value = old["value"]
            if not _values_equal(old_value, new_value):
                trace = EventTrace(
                    court_id=court_id,
                    field_name=field,
                    old_value=old_value,
                    new_value=new_value,
                    start_time=parse_iso(old["start_time"]),
                    end_time=observed_time,
                )
                db.insert_event_trace(trace, observed_time=observed_time)
                db.upsert_field_state(
                    court_id=court_id,
                    field_name=field,
                    value=new_value,
                    start_time=observed_time,
                    last_seen_time=observed_time,
                )
                changes.append(trace)
            else:
                db.touch_field_state(court_id, field, last_seen_time=observed_time)

    return changes

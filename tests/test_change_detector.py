from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eventtrace.change_detector import apply_snapshot
from eventtrace.common.time import parse_iso
from eventtrace.config import Settings
from eventtrace.db import DB


class ChangeDetectorTests(unittest.TestCase):
    def test_apply_snapshot_creates_event_trace_on_change(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as tmp:
            settings = Settings(db_path=tmp.name)
            db = DB(settings.db_path)
            db.ensure_schema()

            t1 = datetime(2026, 5, 2, 0, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 5, 2, 0, 0, 15, tzinfo=timezone.utc)

            apply_snapshot(db, {"A": {"court_no": "A", "judge_names": "J1"}}, observed_time=t1)
            changes = apply_snapshot(db, {"A": {"court_no": "A", "judge_names": "J2"}}, observed_time=t2)

            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].field_name, "judge_names")
            self.assertEqual(changes[0].old_value, "J1")
            self.assertEqual(changes[0].new_value, "J2")

            rows = db.list_event_traces(limit=10, court_id="A")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["field_name"], "judge_names")
            self.assertEqual(rows[0]["old_value"], "J1")
            self.assertEqual(rows[0]["new_value"], "J2")
            self.assertEqual(parse_iso(rows[0]["start_time"]), t1)
            self.assertEqual(parse_iso(rows[0]["end_time"]), t2)

    def test_presence_tracking(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as tmp:
            settings = Settings(db_path=tmp.name)
            db = DB(settings.db_path)
            db.ensure_schema()

            t1 = datetime(2026, 5, 2, 0, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 5, 2, 0, 0, 15, tzinfo=timezone.utc)
            t3 = datetime(2026, 5, 2, 0, 0, 30, tzinfo=timezone.utc)

            # Court 'A' appears
            apply_snapshot(db, {"A": {"court_no": "A"}}, observed_time=t1)
            
            # Court 'A' disappears
            changes_t2 = apply_snapshot(db, {}, observed_time=t2)
            self.assertEqual(len(changes_t2), 1)
            self.assertEqual(changes_t2[0].field_name, "__present__")
            self.assertEqual(changes_t2[0].old_value, "1")
            self.assertEqual(changes_t2[0].new_value, "0")
            
            # Court 'A' reappears
            changes_t3 = apply_snapshot(db, {"A": {"court_no": "A"}}, observed_time=t3)
            self.assertTrue(any(c.field_name == "__present__" and c.new_value == "1" for c in changes_t3))

    def test_dynamic_headers(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as tmp:
            settings = Settings(db_path=tmp.name)
            db = DB(settings.db_path)
            db.ensure_schema()

            t1 = datetime(2026, 5, 2, 0, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 5, 2, 0, 0, 15, tzinfo=timezone.utc)

            # Initial state
            apply_snapshot(db, {"A": {"court_no": "A", "foo": "bar"}}, observed_time=t1)
            
            # Additional column appears
            changes = apply_snapshot(db, {"A": {"court_no": "A", "foo": "bar", "baz": "qux"}}, observed_time=t2)
            
            # The system correctly treats the *first* appearance of a field as initialization
            # and does not generate an EventTrace for it.
            self.assertEqual(len(changes), 0)
            
            # If it changes *after* initialization, it should trigger a trace.
            t3 = datetime(2026, 5, 2, 0, 0, 30, tzinfo=timezone.utc)
            changes_t3 = apply_snapshot(db, {"A": {"court_no": "A", "foo": "bar", "baz": "new_qux"}}, observed_time=t3)
            self.assertEqual(len(changes_t3), 1)
            self.assertEqual(changes_t3[0].field_name, "baz")
            self.assertEqual(changes_t3[0].old_value, "qux")
            self.assertEqual(changes_t3[0].new_value, "new_qux")


if __name__ == "__main__":
    unittest.main()

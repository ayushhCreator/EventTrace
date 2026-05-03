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


if __name__ == "__main__":
    unittest.main()

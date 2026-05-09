from __future__ import annotations

import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eventtrace.monitor.run_monitor import _compress_ranges

class RunMonitorTests(unittest.TestCase):
    def test_compress_ranges(self) -> None:
        self.assertEqual(_compress_ranges([]), "")
        self.assertEqual(_compress_ranges([1]), "1")
        self.assertEqual(_compress_ranges([1, 2, 3]), "1-3")
        self.assertEqual(_compress_ranges([1, 2, 3, 15, 16]), "1-3,15-16")
        self.assertEqual(_compress_ranges([15, 16, 29, 31, 33]), "15-16,29,31,33")
        self.assertEqual(_compress_ranges([1, 3, 5]), "1,3,5")
        # Duplicates and unsorted
        self.assertEqual(_compress_ranges([3, 1, 2, 1, 3]), "1-3")

if __name__ == "__main__":
    unittest.main()

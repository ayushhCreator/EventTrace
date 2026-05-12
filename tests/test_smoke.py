from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
from unittest.mock import patch
import tempfile
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_TEST_ENV = {
    "DATABASE_URL": "",
    "JWT_SECRET": "test-secret-eventtrace-abc123",
    "MSG91_AUTH_KEY": "",
    "MSG91_TEMPLATE_ID": "",
}

def _make_client() -> TestClient:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    env = {**_TEST_ENV, "CHD_DB_PATH": tmp.name}
    with patch.dict(os.environ, env):
        from eventtrace.config import Settings
        from eventtrace.db import get_db
        db = get_db(Settings())
        db.ensure_schema()
        from eventtrace.api import create_app
        app = create_app()
    client = TestClient(app, raise_server_exceptions=True)
    client.db_path = tmp.name  # type: ignore[attr-defined]
    return client

class TestSmoke(unittest.TestCase):
    def setUp(self):
        self.c = _make_client()

    def test_backend_smoke(self):
        """
        Smoke test for backend APIs to ensure the core routing
        and responses are healthy.
        """
        # 1. Healthcheck
        r = self.c.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

        # 2. Check current state (should be empty array in new DB)
        r = self.c.get("/current-state")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

        # 3. Check event traces
        r = self.c.get("/event-traces")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

if __name__ == "__main__":
    unittest.main()

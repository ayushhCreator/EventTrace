from __future__ import annotations

from typing import Any

from .storage.postgres import PostgresDB
from .storage.sqlite import DB


def get_db(settings: Any) -> "DB | PostgresDB":
    """Return DB or PostgresDB based on DATABASE_URL env var."""
    dsn = getattr(settings, "database_url", None)
    if dsn:
        return PostgresDB(dsn)
    return DB(settings.db_path)

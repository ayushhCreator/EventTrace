from __future__ import annotations

from typing import Any


def get_db(settings: Any):
    """Return DB or PostgresDB based on DATABASE_URL env var."""
    dsn = getattr(settings, "database_url", None)
    if dsn:
        from .storage.postgres import PostgresDB

        return PostgresDB(dsn)
    from .storage.sqlite import DB

    return DB(settings.db_path)

from __future__ import annotations

import os

from fastapi import FastAPI, Query

from .config import Settings
from .db import DB


def create_app() -> FastAPI:
    settings = Settings()
    db = DB(settings.db_path)
    db.ensure_schema()

    app = FastAPI(title="CHD Real-Time Monitor", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/current-state")
    def current_state() -> list[dict]:
        return db.list_current_state()

    @app.get("/changes")
    def changes(
        limit: int = Query(200, ge=1, le=2000),
        court_id: str | None = None,
    ) -> list[dict]:
        # Backward-compatible endpoint
        return db.list_event_traces(limit=limit, court_id=court_id)

    @app.get("/event-traces")
    def event_traces(
        limit: int = Query(200, ge=1, le=2000),
        court_id: str | None = None,
    ) -> list[dict]:
        return db.list_event_traces(limit=limit, court_id=court_id)

    @app.get("/field-state/{court_id}")
    def field_state(court_id: str) -> list[dict]:
        return db.list_field_state(court_id)

    return app


def main() -> None:
    import uvicorn

    settings = Settings()
    host = os.getenv("CHD_API_HOST", "127.0.0.1")
    port = int(os.getenv("CHD_API_PORT", "8009"))
    uvicorn.run("eventtrace.api:create_app", host=host, port=port, factory=True, reload=False)

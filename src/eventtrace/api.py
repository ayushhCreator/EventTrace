from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from .config import Settings
from .db import DB

_UI_PATH = Path(__file__).parent / "ui.html"


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

    @app.get("/history/dates")
    def history_dates() -> list[str]:
        return db.list_active_dates()

    @app.get("/history/day")
    def history_day(date: str = Query(..., description="YYYY-MM-DD in IST")) -> list[dict]:
        return db.list_day_activity(date)

    @app.get("/export/current-state.csv")
    def export_current_state_csv():
        rows = db.list_current_state()
        if not rows:
            return StreamingResponse(io.StringIO("court_id,last_seen_time\n"), media_type="text/csv",
                                     headers={"Content-Disposition": "attachment; filename=current_state.csv"})
        # flatten: court_id + last_seen_time + all data keys
        all_keys: list[str] = []
        for r in rows:
            for k in r["data"].keys():
                if k not in all_keys:
                    all_keys.append(k)
        fieldnames = ["court_id", "last_seen_time"] + all_keys
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            flat = {"court_id": r["court_id"], "last_seen_time": r["last_seen_time"]}
            flat.update(r["data"])
            writer.writerow(flat)
        buf.seek(0)
        return StreamingResponse(buf, media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=current_state.csv"})

    @app.get("/export/event-traces.csv")
    def export_event_traces_csv(
        limit: int = Query(2000, ge=1, le=100000),
        court_id: str | None = None,
    ):
        rows = db.list_event_traces(limit=limit, court_id=court_id)
        fieldnames = ["id", "court_id", "field_name", "old_value", "new_value",
                      "start_time", "end_time", "duration_seconds", "observed_time"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        buf.seek(0)
        return StreamingResponse(buf, media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=event_traces.csv"})

    @app.get("/", response_class=HTMLResponse)
    @app.get("/ui", response_class=HTMLResponse)
    def ui():
        return HTMLResponse(_UI_PATH.read_text())

    return app


def main() -> None:
    import uvicorn

    settings = Settings()
    host = os.getenv("CHD_API_HOST", "127.0.0.1")
    port = int(os.getenv("CHD_API_PORT", "8009"))
    uvicorn.run("eventtrace.api:create_app", host=host, port=port, factory=True, reload=False)

from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from .config import Settings
from .db import DB

_UI_DIR = Path(__file__).parent / "ui"


def _today_ist() -> str:
    """Current date in IST as YYYY-MM-DD."""
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def create_app() -> FastAPI:
    settings = Settings()
    db = DB(settings.db_path)
    db.ensure_schema()

    app = FastAPI(title="CHD EventTrace", version="0.2.0")

    # ── Health ───────────────────────────────────────────────────────────────

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # ── Display board data ───────────────────────────────────────────────────

    @app.get("/current-state")
    def current_state() -> list[dict]:
        return db.list_current_state()

    @app.get("/vc-links")
    def vc_links(date: str | None = Query(None, description="YYYY-MM-DD IST, defaults to today")) -> dict[str, str]:
        return db.get_vc_zoom_links(date or _today_ist())

    # ── Event traces ─────────────────────────────────────────────────────────

    @app.get("/changes")
    @app.get("/event-traces")
    def event_traces(
        limit: int = Query(200, ge=1, le=2000),
        court_id: str | None = None,
    ) -> list[dict]:
        return db.list_event_traces(limit=limit, court_id=court_id)

    @app.get("/field-state/{court_id}")
    def field_state(court_id: str) -> list[dict]:
        return db.list_field_state(court_id)

    @app.get("/field-durations")
    def field_durations() -> dict[str, str]:
        """Returns {court_id: serial_start_time ISO} for all courts."""
        return db.list_serial_start_times()

    # ── History ──────────────────────────────────────────────────────────────

    @app.get("/history/dates")
    def history_dates() -> list[str]:
        return db.list_active_dates()

    @app.get("/history/day")
    def history_day(date: str = Query(..., description="YYYY-MM-DD in IST")) -> list[dict]:
        return db.list_day_activity(date)

    # ── Exports ──────────────────────────────────────────────────────────────

    @app.get("/export/current-state.csv")
    def export_current_state_csv():
        rows = db.list_current_state()
        if not rows:
            return StreamingResponse(
                io.StringIO("court_id,last_seen_time\n"),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=current_state.csv"},
            )
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
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=current_state.csv"},
        )

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
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=event_traces.csv"},
        )

    # ── UI pages ─────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    @app.get("/ui", response_class=HTMLResponse)
    def ui_display():
        return HTMLResponse((_UI_DIR / "index.html").read_text())

    @app.get("/admin", response_class=HTMLResponse)
    def ui_admin():
        return HTMLResponse((_UI_DIR / "admin.html").read_text())

    return app


def main() -> None:
    import uvicorn

    host = os.getenv("CHD_API_HOST", "127.0.0.1")
    port = int(os.getenv("CHD_API_PORT", "8009"))
    reload_env = os.getenv("CHD_API_RELOAD", "0").strip().lower()
    reload_enabled = reload_env in {"1", "true", "yes", "on"}
    uvicorn.run("eventtrace.api:create_app", host=host, port=port, factory=True, reload=reload_enabled)

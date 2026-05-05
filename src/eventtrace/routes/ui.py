from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

_UI_DIR = Path(__file__).resolve().parents[1] / "ui"

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
def ui_display():
    return HTMLResponse((_UI_DIR / "index.html").read_text())


@router.get("/admin", response_class=HTMLResponse)
def ui_admin():
    return HTMLResponse((_UI_DIR / "admin.html").read_text())

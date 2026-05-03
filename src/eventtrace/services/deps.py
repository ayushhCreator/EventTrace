from __future__ import annotations

from typing import Any

from fastapi import Request

from ..config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[return-value]


def get_db(request: Request) -> Any:
    return request.app.state.db


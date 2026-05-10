from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import Settings
from .db import get_db
from .routes.alerts import router as alerts_router
from .routes.auth import router as auth_router
from .routes.causelist import router as causelist_router
from .routes.display import router as display_router
from .routes.export import router as export_router
from .routes.health import router as health_router
from .routes.history import router as history_router
from .routes.matters import router as matters_router
from .routes.my_cases import router as my_cases_router, timeline_router
from .routes.ui import router as ui_router
from .routes.webhooks import router as webhooks_router

limiter = Limiter(key_func=get_remote_address)


def create_app() -> FastAPI:
    settings = Settings()
    db = get_db(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.ensure_schema()
        yield

    app = FastAPI(title="CHD EventTrace", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    _default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://supersahayak.web.app",
        "https://supersahayak.firebaseapp.com",
        "https://legal.supersahayak.com",
        "https://www.legal.supersahayak.com",
    ]
    _extra = [o.strip() for o in os.getenv("CHD_CORS_ORIGINS", "").split(",") if o.strip()]
    _origins = _default_origins + _extra

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(display_router)
    app.include_router(history_router)
    app.include_router(export_router)
    app.include_router(alerts_router)
    app.include_router(webhooks_router)
    app.include_router(causelist_router)
    app.include_router(auth_router)
    app.include_router(my_cases_router)
    app.include_router(timeline_router)
    app.include_router(matters_router)
    app.include_router(ui_router)

    return app


def main() -> None:
    from .core.logging_setup import configure_logging
    configure_logging()

    import uvicorn

    host = os.getenv("CHD_API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("CHD_API_PORT", "8009"))
    reload_env = os.getenv("CHD_API_RELOAD", "0").strip().lower()
    reload_enabled = reload_env in {"1", "true", "yes", "on"}
    uvicorn.run(
        "eventtrace.api:create_app", host=host, port=port, factory=True, reload=reload_enabled
    )

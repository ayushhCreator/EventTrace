from __future__ import annotations

import os
from pathlib import Path

# Auto-load .env from project root (non-fatal if missing or dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent.parent / ".env", override=False)
except ImportError:
    pass


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings:
    def __init__(
        self,
        *,
        url: str | None = None,
        table_selector: str | None = None,
        key_fields: tuple[str, ...] | None = None,
        poll_seconds: int | None = None,
        db_path: str | None = None,
        storage_state_path: str | None = None,
        headless: bool | None = None,
        telegram_token: str | None = None,
    ) -> None:
        self.url = url or _get_env("CHD_URL", "https://display.calcuttahighcourt.gov.in/principal.php")
        self.table_selector = table_selector or _get_env("CHD_TABLE_SELECTOR", "table")
        if key_fields is None:
            key_fields = tuple(
                f.strip()
                for f in _get_env("CHD_KEY_FIELDS", "court_no").split(",")
                if f.strip()
            )
        self.key_fields = key_fields
        self.poll_seconds = poll_seconds if poll_seconds is not None else _get_env_int("CHD_POLL_SECONDS", 15)
        self.db_path = db_path or _get_env("CHD_DB_PATH", "./data/eventtrace.sqlite3")
        self.storage_state_path = storage_state_path or _get_env(
            "CHD_STORAGE_STATE_PATH", "./.state/storage_state.json"
        )
        self.headless = headless if headless is not None else _get_env_bool("CHD_HEADLESS", True)
        self.telegram_token = telegram_token or _get_env("TELEGRAM_TOKEN", "")
        self.twilio_account_sid = _get_env("TWILIO_ACCOUNT_SID", "")
        self.twilio_auth_token = _get_env("TWILIO_AUTH_TOKEN", "")
        # e.g. "whatsapp:+14155238886"  (sandbox) or dedicated number
        self.twilio_whatsapp_from = _get_env("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
        # Bot username used to build deep links e.g. "Eventtrace_bot"
        self.telegram_bot_username = _get_env("TELEGRAM_BOT_USERNAME", "Eventtrace_bot")
        # Public base URL for webhook signature verification (e.g. https://abc.ngrok-free.app)
        self.public_url = _get_env("CHD_PUBLIC_URL", "")
        # PostgreSQL DSN — if set, all processes use Postgres instead of SQLite
        # e.g. postgresql://user:pass@localhost:5432/eventtrace
        self.database_url = _get_env("DATABASE_URL", "") or None
        # Telegram chat ID for admin alerts (causelist scrape failures etc.)
        self.admin_chat_id = _get_env("ADMIN_CHAT_ID", "") or None
        # MSG91 — OTP delivery
        self.msg91_auth_key = _get_env("MSG91_AUTH_KEY", "")
        self.msg91_template_id = _get_env("MSG91_TEMPLATE_ID", "")
        # JWT signing secret — generate with: python -c "import secrets; print(secrets.token_hex(32))"
        self.jwt_secret = _get_env("JWT_SECRET", "change-me-in-production")
        if self.jwt_secret == "change-me-in-production" and self.msg91_auth_key:
            raise RuntimeError(
                "JWT_SECRET must be set in production (MSG91_AUTH_KEY is set but JWT_SECRET is default). "
                "Run: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

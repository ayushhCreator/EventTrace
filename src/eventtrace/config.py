from __future__ import annotations

import os
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
        self.db_path = db_path or _get_env("CHD_DB_PATH", "./eventtrace.sqlite3")
        self.storage_state_path = storage_state_path or _get_env(
            "CHD_STORAGE_STATE_PATH", "./.state/storage_state.json"
        )
        self.headless = headless if headless is not None else _get_env_bool("CHD_HEADLESS", True)

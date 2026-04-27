from __future__ import annotations

import ssl
from typing import Any

import httpx

from .config import Settings

_API_URL = "https://display.calcuttahighcourt.gov.in/display_api.json"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": "https://display.calcuttahighcourt.gov.in/principal.php",
}

# Server uses legacy TLS renegotiation; Python 3.10+ disables it by default.
def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    return ctx


def scrape_table_once_sync(settings: Settings) -> list[dict[str, Any]]:
    with httpx.Client(verify=_ssl_ctx(), timeout=10) as client:
        r = client.get(_API_URL, headers=_HEADERS)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

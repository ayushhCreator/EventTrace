from __future__ import annotations

from typing import Any


def normalize_header(header: str) -> str:
    return " ".join(header.replace("\n", " ").split()).strip()


def normalize_cell(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = " ".join(text.replace("\n", " ").split()).strip()
    return text if text != "" else None


def normalize_row(row: dict[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for k, v in row.items():
        out[normalize_header(str(k))] = normalize_cell(v)
    return out


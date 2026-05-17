"""Reconciliation job — match causelist entries against display board snapshots.

Confidence scoring (spec §MODULE 1):
  Match on (court_id, case_number, hearing_date):
    3/3 → HIGH   → auto-approve for notification
    2/3 → MEDIUM → flag for admin review, hold VC link
    1/3 → LOW    → skip entirely

SOLID:
  - Single Responsibility: pure _score() is separate from I/O reconcile_entry().
  - Open/Closed: add a new field to scoring by extending _SCORE_EXTRACTORS,
    no changes to reconcile_entry.
DRY: _parse_snapshot_json() used in both _score() and run_reconciliation_batch().
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()

# ── Field extractors (Open/Closed) ────────────────────────────────────────────
# Each extractor returns (entry_val, snap_val) as normalised strings.
# Add a new entry here to score on an additional field — zero changes elsewhere.

def _norm(s: str | None) -> str:
    return (s or "").strip().lower().replace(" ", "")


_SCORE_EXTRACTORS = [
    (
        "court_id",
        lambda e, s: _norm(e.get("court_id")),
        lambda e, s: _norm(s.get("court_id") or s.get("court_no")),
    ),
    (
        "case_number",
        lambda e, s: _norm(e.get("case_number")),
        lambda e, s: _norm(s.get("case_number") or s.get("case_ref")),
    ),
    (
        "hearing_date",
        lambda e, s: (e.get("hearing_date") or "").strip(),
        lambda e, s: (s.get("hearing_date") or s.get("list_date") or "").strip(),
    ),
]


# ── Pure functions ────────────────────────────────────────────────────────────


def _parse_snapshot_json(raw: str | dict | None) -> dict:
    """Safely parse snapshot_json from string or passthrough if already dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def score(entry: dict, snap_data: dict) -> tuple[str, list[str]]:
    """Return (confidence, matched_fields) for one entry/snapshot pair.

    Pure function — no I/O. Fully testable.
    """
    matched: list[str] = []
    for field_name, get_entry, get_snap in _SCORE_EXTRACTORS:
        ev = get_entry(entry, snap_data)
        sv = get_snap(entry, snap_data)
        if ev and sv and ev == sv:
            matched.append(field_name)

    n = len(matched)
    if n >= 3:
        return "HIGH", matched
    if n == 2:
        return "MEDIUM", matched
    return "LOW", matched


# ── I/O ───────────────────────────────────────────────────────────────────────


def reconcile_entry(
    db: Any,
    causelist_entry: dict,
    snapshot: dict,
    vc_link_id: str | None = None,
    source_court: str = "CHD",
) -> dict:
    """Reconcile one causelist entry against one display board snapshot.

    Writes a ReconciliationResult row regardless of confidence (caller filters).
    Returns the result dict.
    """
    snap_data = _parse_snapshot_json(snapshot.get("snapshot_json"))
    confidence, matched_fields = score(causelist_entry, snap_data)
    now = datetime.now(timezone.utc).isoformat()
    result_id = str(uuid.uuid4())

    try:
        db.create_reconciliation_result(
            id=result_id,
            source_court=source_court,
            causelist_entry_id=causelist_entry.get("id"),
            display_board_snapshot_id=snapshot.get("id"),
            confidence=confidence,
            matched_fields=json.dumps(matched_fields),
            vc_link_id=vc_link_id,
            created_at=now,
        )
        log.info(
            "reconciliation: result written",
            result_id=result_id,
            confidence=confidence,
            matched_fields=matched_fields,
            source_court=source_court,
        )
    except Exception as exc:
        log.error("reconciliation: db write failed", exc=str(exc))

    return {
        "id": result_id,
        "source_court": source_court,
        "causelist_entry_id": causelist_entry.get("id"),
        "display_board_snapshot_id": snapshot.get("id"),
        "confidence": confidence,
        "matched_fields": matched_fields,
        "vc_link_id": vc_link_id,
        "created_at": now,
    }


def run_reconciliation_batch(
    db: Any,
    entries: list[dict],
    snapshots: list[dict],
    vc_link_id: str | None = None,
    source_court: str = "CHD",
) -> list[dict]:
    """Find best snapshot per entry; write result only for HIGH or MEDIUM matches.

    O(n*m) — fine for court-day-sized batches (hundreds of entries).
    """
    _WRITE_CONFIDENCES = frozenset(("HIGH", "MEDIUM"))
    results: list[dict] = []

    # Pre-parse all snapshot JSONs once (DRY — avoids re-parsing per entry)
    parsed_snaps = [
        (snap, _parse_snapshot_json(snap.get("snapshot_json")))
        for snap in snapshots
    ]

    for entry in entries:
        best: tuple[str, dict, list[str]] | None = None  # (confidence, snap, fields)

        for snap, snap_data in parsed_snaps:
            conf, fields = score(entry, snap_data)
            if conf == "HIGH":
                best = (conf, snap, fields)
                break
            if conf == "MEDIUM" and (best is None or best[0] != "HIGH"):
                best = (conf, snap, fields)

        if best and best[0] in _WRITE_CONFIDENCES:
            _, best_snap, _ = best
            result = reconcile_entry(db, entry, best_snap, vc_link_id, source_court)
            results.append(result)

    log.info(
        "reconciliation batch done",
        entries=len(entries),
        snapshots=len(snapshots),
        results=len(results),
        source_court=source_court,
    )
    return results

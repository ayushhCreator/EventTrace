"""Reconciliation job — match causelist entries against display board snapshots.

Spec §MODULE 1 (confidence scoring):
  Match on (court_id, case_number, hearing_date):
    3/3 → HIGH   — auto-approve for notification
    2/3 → MEDIUM — flag for admin review, hold VC link
    1/3 → LOW    — do not use for notification at all

Writes one ReconciliationResult row per matched pair.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()


def _score(entry: dict, snapshot_data: dict) -> tuple[str, list[str]]:
    """Score one causelist entry against one display board snapshot payload.

    snapshot_data: parsed JSON from DisplayBoardSnapshot.snapshot_json.
    Returns (confidence, matched_fields_list).
    """
    matched: list[str] = []

    entry_court = (entry.get("court_id") or "").strip().lower()
    snap_court = (snapshot_data.get("court_id") or snapshot_data.get("court_no") or "").strip().lower()
    if entry_court and snap_court and entry_court == snap_court:
        matched.append("court_id")

    entry_case = (entry.get("case_number") or "").strip().lower().replace(" ", "")
    snap_case = (snapshot_data.get("case_number") or snapshot_data.get("case_ref") or "").strip().lower().replace(" ", "")
    if entry_case and snap_case and entry_case == snap_case:
        matched.append("case_number")

    entry_date = (entry.get("hearing_date") or "").strip()
    snap_date = (snapshot_data.get("hearing_date") or snapshot_data.get("list_date") or "").strip()
    if entry_date and snap_date and entry_date == snap_date:
        matched.append("hearing_date")

    n = len(matched)
    if n >= 3:
        confidence = "HIGH"
    elif n == 2:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return confidence, matched


def reconcile_entry(
    db: Any,
    causelist_entry: dict,
    snapshot: dict,
    vc_link_id: str | None = None,
) -> dict:
    """Reconcile one causelist entry against one display board snapshot.

    causelist_entry: dict with keys: id, court_id, case_number, hearing_date
    snapshot: dict with keys: id, snapshot_json (JSON string or dict)

    Returns the created ReconciliationResult as a dict.
    """
    snap_data = snapshot.get("snapshot_json") or {}
    if isinstance(snap_data, str):
        try:
            snap_data = json.loads(snap_data)
        except Exception:
            snap_data = {}

    confidence, matched_fields = _score(causelist_entry, snap_data)
    now = datetime.now(timezone.utc).isoformat()
    result_id = str(uuid.uuid4())

    try:
        db.create_reconciliation_result(
            id=result_id,
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
        )
    except Exception as exc:
        log.error("reconciliation: db write failed", exc=str(exc))

    return {
        "id": result_id,
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
) -> list[dict]:
    """Reconcile a batch of causelist entries against display board snapshots.

    For each entry, finds the best-matching snapshot (highest confidence).
    Only writes a result row when confidence is HIGH or MEDIUM.
    Returns list of result dicts.
    """
    results: list[dict] = []
    for entry in entries:
        best_conf = "LOW"
        best_snap: dict | None = None
        best_fields: list[str] = []

        for snap in snapshots:
            snap_data = snap.get("snapshot_json") or {}
            if isinstance(snap_data, str):
                try:
                    snap_data = json.loads(snap_data)
                except Exception:
                    snap_data = {}
            conf, fields = _score(entry, snap_data)
            if conf == "HIGH":
                best_conf, best_snap, best_fields = conf, snap, fields
                break
            if conf == "MEDIUM" and best_conf != "HIGH":
                best_conf, best_snap, best_fields = conf, snap, fields

        if best_snap is not None and best_conf in ("HIGH", "MEDIUM"):
            result = reconcile_entry(db, entry, best_snap, vc_link_id)
            results.append(result)

    log.info(
        "reconciliation batch done",
        entries=len(entries),
        snapshots=len(snapshots),
        results=len(results),
    )
    return results

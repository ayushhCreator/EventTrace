"""Add source_court to all Phase 1A tables for multi-court support

Revision ID: 0016_source_court
Revises: 0015_phase1a
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_source_court"
down_revision: Union[str, None] = "0015_phase1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that need source_court added, with default value and nullable flag.
# AdminAlert is nullable (system-wide alerts may not be court-specific).
_TABLES_NOT_NULL: list[str] = [
    "causelist_entries",
    "vc_links",
    "vc_link_delivery_log",
    "display_board_snapshots",
    "reconciliation_results",
]
_TABLES_NULLABLE: list[str] = [
    "admin_alerts",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    for table in _TABLES_NOT_NULL:
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if "source_court" not in existing_cols:
            op.add_column(
                table,
                sa.Column("source_court", sa.String(10), nullable=False, server_default="CHD"),
            )

    for table in _TABLES_NULLABLE:
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if "source_court" not in existing_cols:
            op.add_column(
                table,
                sa.Column("source_court", sa.String(10), nullable=True),
            )

    # Replace old single-column indexes with multi-court-aware compound indexes
    # (best-effort — skip if already exists or table absent)
    pg = bind.dialect.name == "postgresql"
    _try_create_index(bind, pg, "idx_ce_source_court_date", "causelist_entries", ["source_court", "court_id", "hearing_date"])
    _try_create_index(bind, pg, "idx_vc_links_source_court", "vc_links", ["source_court", "court_id"])
    _try_create_index(bind, pg, "idx_vcdl_source_court", "vc_link_delivery_log", ["source_court", "case_number"])
    _try_create_index(bind, pg, "idx_dbs_source_court_time", "display_board_snapshots", ["source_court", "court_id", "captured_at"])
    _try_create_index(bind, pg, "idx_admin_alerts_source_court", "admin_alerts", ["source_court", "resolved", "created_at"])
    _try_create_index(bind, pg, "idx_recon_source_court_conf", "reconciliation_results", ["source_court", "confidence"])

    # Drop now-superseded single-column indexes if they exist
    existing_tables_set = set(existing_tables)
    _try_drop_index(bind, pg, "idx_ce_court_date", "causelist_entries", existing_tables_set)
    _try_drop_index(bind, pg, "idx_vc_links_court", "vc_links", existing_tables_set)
    _try_drop_index(bind, pg, "idx_vcdl_case", "vc_link_delivery_log", existing_tables_set)
    _try_drop_index(bind, pg, "idx_dbs_court_time", "display_board_snapshots", existing_tables_set)
    _try_drop_index(bind, pg, "idx_admin_alerts_resolved_at", "admin_alerts", existing_tables_set)
    _try_drop_index(bind, pg, "idx_recon_confidence", "reconciliation_results", existing_tables_set)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    for table in _TABLES_NOT_NULL + _TABLES_NULLABLE:
        if table not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if "source_court" in existing_cols:
            op.drop_column(table, "source_court")


# ── helpers ───────────────────────────────────────────────────────────────────

def _try_create_index(bind, pg: bool, name: str, table: str, cols: list[str]) -> None:
    if table not in {t for t in sa.inspect(bind).get_table_names()}:
        return
    existing = {i["name"] for i in sa.inspect(bind).get_indexes(table)}
    if name not in existing:
        try:
            op.create_index(name, table, cols)
        except Exception:
            pass


def _try_drop_index(bind, pg: bool, name: str, table: str, existing_tables: set) -> None:
    if table not in existing_tables:
        return
    existing = {i["name"] for i in sa.inspect(bind).get_indexes(table)}
    if name in existing:
        try:
            op.drop_index(name, table_name=table)
        except Exception:
            pass

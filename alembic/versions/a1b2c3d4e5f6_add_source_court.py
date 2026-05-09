"""add_source_court

Revision ID: a1b2c3d4e5f6
Revises: ec9ae990e181
Create Date: 2026-05-09

Add source_court column to current_state, field_state, event_trace, causelist_bench.
Backfills all existing rows to 'CHD' (Calcutta HC — the only court scraped to date).
Required before adding any second court to avoid ambiguous court_id values.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "ec9ae990e181"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── current_state ────────────────────────────────────────────────────────
    with op.batch_alter_table("current_state") as batch_op:
        batch_op.add_column(
            sa.Column("source_court", sa.String(), nullable=False, server_default="CHD")
        )
    op.execute("UPDATE current_state SET source_court = 'CHD'")
    with op.batch_alter_table("current_state") as batch_op:
        batch_op.create_index("idx_current_state_source_court", ["source_court", "court_id"])

    # ── field_state ──────────────────────────────────────────────────────────
    with op.batch_alter_table("field_state") as batch_op:
        batch_op.add_column(
            sa.Column("source_court", sa.String(), nullable=False, server_default="CHD")
        )
    op.execute("UPDATE field_state SET source_court = 'CHD'")
    with op.batch_alter_table("field_state") as batch_op:
        batch_op.create_index(
            "idx_field_state_source_court", ["source_court", "court_id", "field_name"]
        )

    # ── event_trace ──────────────────────────────────────────────────────────
    with op.batch_alter_table("event_trace") as batch_op:
        batch_op.add_column(
            sa.Column("source_court", sa.String(), nullable=False, server_default="CHD")
        )
    op.execute("UPDATE event_trace SET source_court = 'CHD'")
    with op.batch_alter_table("event_trace") as batch_op:
        batch_op.create_index(
            "idx_event_trace_source_court", ["source_court", "court_id", "observed_time"]
        )

    # ── causelist_bench ──────────────────────────────────────────────────────
    with op.batch_alter_table("causelist_bench") as batch_op:
        batch_op.add_column(
            sa.Column("source_court", sa.String(), nullable=False, server_default="CHD")
        )
    op.execute("UPDATE causelist_bench SET source_court = 'CHD'")
    with op.batch_alter_table("causelist_bench") as batch_op:
        batch_op.create_index(
            "idx_causelist_bench_source_court", ["source_court", "list_date", "court_no"]
        )


def downgrade() -> None:
    with op.batch_alter_table("causelist_bench") as batch_op:
        batch_op.drop_index("idx_causelist_bench_source_court")
        batch_op.drop_column("source_court")

    with op.batch_alter_table("event_trace") as batch_op:
        batch_op.drop_index("idx_event_trace_source_court")
        batch_op.drop_column("source_court")

    with op.batch_alter_table("field_state") as batch_op:
        batch_op.drop_index("idx_field_state_source_court")
        batch_op.drop_column("source_court")

    with op.batch_alter_table("current_state") as batch_op:
        batch_op.drop_index("idx_current_state_source_court")
        batch_op.drop_column("source_court")

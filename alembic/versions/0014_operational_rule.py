"""operational_rule: promote scheduling_notes_json into queryable rows

Revision ID: 0014_operational_rule
Revises: 0013_canonical_entities
Create Date: 2026-05-15

scheduling_notes_json stores extracted NOTE: blocks as a JSON blob on every
causelist_bench. This table promotes that blob into structured rows so that
queries like "which courts hear PIL on Monday?" or "which courts start at 2PM?"
are a single indexed SQL query rather than a full-table JSON scan.

Rule types:
  DAY_ORDER    — ordered category list for a specific day of week
  HEARING_TIME — when main/afternoon hearing starts (distinct from bench start)
  MENTIONING   — mentioning allowed (bool encoded as presence of this row)
  RAW_NOTE     — verbatim numbered note (I, II, III …) for display + full-text search
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_operational_rule"
down_revision = "0013_canonical_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_rule",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "bench_id",
            sa.BigInteger(),
            sa.ForeignKey("causelist_bench.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_type", sa.String(), nullable=False),
        sa.Column("day_of_week", sa.String(), nullable=True),
        sa.Column("category_order_json", sa.Text(), nullable=True),
        sa.Column("time_value", sa.String(), nullable=True),
        sa.Column("raw_note", sa.Text(), nullable=True),
        sa.Column("note_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("idx_op_rule_bench", "operational_rule", ["bench_id"])
    op.create_index("idx_op_rule_type", "operational_rule", ["rule_type"])
    op.create_index("idx_op_rule_day", "operational_rule", ["day_of_week"])


def downgrade() -> None:
    op.drop_index("idx_op_rule_day", "operational_rule")
    op.drop_index("idx_op_rule_type", "operational_rule")
    op.drop_index("idx_op_rule_bench", "operational_rule")
    op.drop_table("operational_rule")

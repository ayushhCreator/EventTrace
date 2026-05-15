"""causelist_bench: include at_time in unique key to preserve multi-slot courts

Revision ID: 0010_causelist_bench_at_time_key
Revises: 0009_ecourts_case_type_map
Create Date: 2026-05-15

Problem: courts like Court 1 sit multiple times per day at different times
(02:00 PM, 02:15 PM, 10:30 AM…). All slots share the same
(list_date, court_no, side, list_type) so all but the last were silently
overwritten — losing ~279 cases per daily scrape on today's list.

Fix: add at_time to the unique key. NULLs become '' so the constraint works.
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_causelist_bench_at_time_key"
down_revision = "0009_ecourts_case_type_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalise NULLs so the new NOT NULL column is consistent
    op.execute("UPDATE causelist_bench SET at_time = '' WHERE at_time IS NULL")
    op.alter_column("causelist_bench", "at_time",
                    existing_type=sa.Text(),
                    nullable=False,
                    server_default="")

    # Drop old 4-column constraint, replace with 5-column one including at_time
    op.drop_constraint("uq_causelist_bench", "causelist_bench", type_="unique")
    op.create_unique_constraint(
        "uq_causelist_bench",
        "causelist_bench",
        ["list_date", "court_no", "side", "list_type", "at_time"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_causelist_bench", "causelist_bench", type_="unique")
    op.create_unique_constraint(
        "uq_causelist_bench",
        "causelist_bench",
        ["list_date", "court_no", "side", "list_type"],
    )
    op.alter_column("causelist_bench", "at_time",
                    existing_type=sa.Text(),
                    nullable=True,
                    server_default=None)

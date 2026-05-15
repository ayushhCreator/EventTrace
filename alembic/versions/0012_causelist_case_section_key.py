"""causelist_case: include section in unique key to preserve multi-section serials

Revision ID: 0012_case_section_key
Revises: 0011_bench_label_key
Create Date: 2026-05-15

Problem: some courts (e.g. Court 7) have a main causelist followed by a
"WARNING LIST" section, each starting serial numbering from 1. With the old
key (bench_id, serial_no), the second section's cases overwrote the first
section's cases 1..N.

Fix: change the unique key to (bench_id, COALESCE(section,''), serial_no)
using a functional unique index so NULL section is treated as empty string.
"""
from alembic import op


revision = "0012_case_section_key"
down_revision = "0011_bench_label_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_causelist_case", "causelist_case", type_="unique")
    op.execute("""
        CREATE UNIQUE INDEX uq_causelist_case
        ON causelist_case(bench_id, COALESCE(section, ''), serial_no)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_causelist_case")
    op.create_unique_constraint(
        "uq_causelist_case",
        "causelist_case",
        ["bench_id", "serial_no"],
    )

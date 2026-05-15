"""causelist_bench: add bench_label to unique key for same-time multi-bench courts

Revision ID: 0011_causelist_bench_bench_label_key
Revises: 0010_causelist_bench_at_time_key
Create Date: 2026-05-15

Problem: some courts host multiple benches at the *same* time slot (e.g.
Court 37 has DB-IV, DB-IV Commercial, and SB all at 10:30 AM; Court 13 has
both a DB and SB at 2:00 PM). The previous key (…, at_time) still collapsed
them into one row, losing the other benches' cases.

Fix: add bench_label to the unique key. bench_label is normalised (NULL→'',
trailing space before ')' stripped) before insert so 'DIVISION BENCH (DB )'
and 'DIVISION BENCH (DB)' are treated identically.
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_bench_label_key"
down_revision = "0010_causelist_bench_at_time_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalise bench_label: NULL → '', strip trailing space before ')'
    op.execute("UPDATE causelist_bench SET bench_label = '' WHERE bench_label IS NULL")
    op.execute(r"UPDATE causelist_bench SET bench_label = TRIM(REGEXP_REPLACE(bench_label, '\s+\)', ')')) WHERE bench_label LIKE '% )'")
    op.alter_column("causelist_bench", "bench_label",
                    existing_type=sa.Text(),
                    nullable=False,
                    server_default="")

    op.drop_constraint("uq_causelist_bench", "causelist_bench", type_="unique")
    op.create_unique_constraint(
        "uq_causelist_bench",
        "causelist_bench",
        ["list_date", "court_no", "side", "list_type", "at_time", "bench_label"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_causelist_bench", "causelist_bench", type_="unique")
    op.create_unique_constraint(
        "uq_causelist_bench",
        "causelist_bench",
        ["list_date", "court_no", "side", "list_type", "at_time"],
    )
    op.alter_column("causelist_bench", "bench_label",
                    existing_type=sa.Text(),
                    nullable=True,
                    server_default=None)

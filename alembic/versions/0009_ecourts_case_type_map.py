"""ecourts_case_type_map — cache prefix→type_id per bench

Revision ID: 0009_ecourts_case_type_map
Revises: 0008_unique_email
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_ecourts_case_type_map"
down_revision = "0008_unique_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ecourts_case_type_map",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("state_cd", sa.Text, nullable=False),
        sa.Column("court_code", sa.Text, nullable=False),
        sa.Column("type_id", sa.Text, nullable=False),
        sa.Column("type_name", sa.Text, nullable=False),
        # Short prefix learned from actual search results (e.g. "CPAN")
        # NULL until a real search confirms it
        sa.Column("prefix", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.Text, nullable=False),
        sa.UniqueConstraint("state_cd", "court_code", "type_id", name="uq_ecourts_type"),
    )
    op.create_index(
        "idx_ecourts_type_prefix",
        "ecourts_case_type_map",
        ["state_cd", "court_code", "prefix"],
    )


def downgrade() -> None:
    op.drop_table("ecourts_case_type_map")

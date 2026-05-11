"""add bar_enrollment_number, firm_name, secondary_email, is_admin to users

Revision ID: 0003_add_user_profile_fields
Revises: 0002_add_refresh_tokens
Create Date: 2026-05-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_user_profile_fields"
down_revision: Union[str, None] = "0002_add_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns("users")}
    if "bar_enrollment_number" not in existing:
        op.add_column("users", sa.Column("bar_enrollment_number", sa.String(), nullable=True))
    if "firm_name" not in existing:
        op.add_column("users", sa.Column("firm_name", sa.String(), nullable=True))
    if "secondary_email" not in existing:
        op.add_column("users", sa.Column("secondary_email", sa.String(), nullable=True))
    if "is_admin" not in existing:
        op.add_column("users", sa.Column("is_admin", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "is_admin")
    op.drop_column("users", "secondary_email")
    op.drop_column("users", "firm_name")
    op.drop_column("users", "bar_enrollment_number")

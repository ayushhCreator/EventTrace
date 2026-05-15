"""unique email per user (partial index, allows NULL)

Revision ID: 0008_unique_email
Revises: 0007_notification_system
Create Date: 2026-05-15
"""
from alembic import op

revision = "0008_unique_email"
down_revision = "0007_notification_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial unique index: only enforces uniqueness on non-NULL emails.
    # NULL emails (users who haven't set one) are freely allowed.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email "
        "ON users (lower(email)) WHERE email IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email")

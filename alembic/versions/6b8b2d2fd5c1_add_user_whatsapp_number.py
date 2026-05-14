"""add_user_whatsapp_number

Revision ID: 6b8b2d2fd5c1
Revises: 4558de5b9871
Create Date: 2026-05-14

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b8b2d2fd5c1"
down_revision: Union[str, Sequence[str], None] = "4558de5b9871"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("whatsapp_number", sa.String(), nullable=True))
    op.execute("UPDATE users SET whatsapp_number = phone WHERE whatsapp_number IS NULL")


def downgrade() -> None:
    op.drop_column("users", "whatsapp_number")


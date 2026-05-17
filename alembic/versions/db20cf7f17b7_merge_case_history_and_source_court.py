"""merge_case_history_and_source_court

Revision ID: db20cf7f17b7
Revises: 0017_recreate_case_history_cache, 5ff818b70039
Create Date: 2026-05-18 01:16:55.654587

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db20cf7f17b7'
down_revision: Union[str, Sequence[str], None] = ('0017_recreate_case_history_cache', '5ff818b70039')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

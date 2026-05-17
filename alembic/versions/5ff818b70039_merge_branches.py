"""merge_branches

Revision ID: 5ff818b70039
Revises: 0014_operational_rule, 0016_source_court
Create Date: 2026-05-17 13:01:50.168742

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ff818b70039'
down_revision: Union[str, Sequence[str], None] = ('0014_operational_rule', '0016_source_court')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

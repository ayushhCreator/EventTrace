"""create all tables

Revision ID: 0001_create_all
Revises:
Create Date: 2026-05-10

"""
from typing import Sequence, Union
from alembic import op

revision: str = "0001_create_all"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from src.eventtrace.storage.models import Base
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from src.eventtrace.storage.models import Base
    Base.metadata.drop_all(bind=op.get_bind())

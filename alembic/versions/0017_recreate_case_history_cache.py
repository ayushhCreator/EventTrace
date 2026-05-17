"""recreate_case_history_cache

Revision ID: 0017_recreate_case_history_cache
Revises: 4558de5b9871
Create Date: 2026-05-18

Migration 4558de5b9871 incorrectly dropped case_history_cache in its upgrade().
This migration recreates the table so the application can function.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0017_recreate_case_history_cache'
down_revision: Union[str, Sequence[str], None] = '4558de5b9871'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'case_history_cache',
        sa.Column('cino', sa.TEXT(), nullable=False),
        sa.Column('state_cd', sa.TEXT(), nullable=False),
        sa.Column('court_code', sa.TEXT(), nullable=False),
        sa.Column('case_type_id', sa.TEXT(), nullable=True),
        sa.Column('case_no', sa.TEXT(), nullable=True),
        sa.Column('case_year', sa.TEXT(), nullable=True),
        sa.Column('data_json', sa.TEXT(), nullable=False),
        sa.Column('fetched_at', sa.TEXT(), nullable=False),
        sa.PrimaryKeyConstraint('cino', 'state_cd', 'court_code', name='case_history_cache_pkey'),
    )
    op.create_index(
        'idx_case_history_cache_fetched',
        'case_history_cache',
        [sa.literal_column('fetched_at DESC')],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_case_history_cache_fetched', table_name='case_history_cache')
    op.drop_table('case_history_cache')

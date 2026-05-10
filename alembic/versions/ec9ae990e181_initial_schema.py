"""initial_schema

Revision ID: ec9ae990e181
Revises: 
Create Date: 2026-05-09 22:26:31.751572

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ec9ae990e181'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from src.eventtrace.storage.models import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Downgrade schema."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from src.eventtrace.storage.models import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)


def _old_upgrade_unused() -> None:
    op.alter_column('case_snapshots', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('case_snapshots', 'list_date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('case_snapshots', 'hash',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('case_snapshots', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_constraint(op.f('case_snapshots_case_ref_list_date_key'), 'case_snapshots', type_='unique')
    op.create_unique_constraint('uq_case_snapshot', 'case_snapshots', ['case_ref', 'list_date'])
    op.alter_column('case_timeline_events', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('case_timeline_events', 'user_id',
               existing_type=sa.UUID(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('case_timeline_events', 'event_type',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('case_timeline_events', 'event_date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('case_timeline_events', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.create_foreign_key(None, 'case_timeline_events', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.alter_column('causelist_bench', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('causelist_bench', 'list_date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('causelist_bench', 'court_no',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('causelist_bench', 'side',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               nullable=False)
    op.alter_column('causelist_bench', 'list_type',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               nullable=False)
    op.alter_column('causelist_bench', 'jurisdiction',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'scraped_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('causelist_bench', 'source_id',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'at_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'floor',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'building',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.drop_constraint(op.f('causelist_bench_unique_source'), 'causelist_bench', type_='unique')
    op.create_unique_constraint('uq_causelist_bench', 'causelist_bench', ['list_date', 'court_no', 'side', 'list_type'])
    op.alter_column('causelist_case', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('causelist_case', 'bench_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'list_date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'court_no',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'case_type',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'case_number',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'section',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'subsection',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'hearing_type',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'scraped_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.drop_constraint(op.f('causelist_case_bench_id_serial_no_key'), 'causelist_case', type_='unique')
    op.drop_index(op.f('idx_cc_advocate_trgm'), table_name='causelist_case', postgresql_ops={'advocate': 'gin_trgm_ops'}, postgresql_using='gin')
    op.drop_index(op.f('idx_cc_petitioner_trgm'), table_name='causelist_case', postgresql_ops={'petitioner': 'gin_trgm_ops'}, postgresql_using='gin')
    op.drop_index(op.f('idx_cc_respondent_trgm'), table_name='causelist_case', postgresql_ops={'respondent': 'gin_trgm_ops'}, postgresql_using='gin')
    op.create_unique_constraint('uq_causelist_case', 'causelist_case', ['bench_id', 'serial_no'])
    op.alter_column('current_state', 'court_id',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('current_state', 'last_seen_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('event_trace', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('event_trace', 'court_id',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('event_trace', 'field_name',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('event_trace', 'start_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('event_trace', 'end_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('event_trace', 'observed_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.drop_index(op.f('idx_event_trace_court'), table_name='event_trace')
    op.create_index('idx_event_trace_court', 'event_trace', ['court_id', 'observed_time'], unique=False)
    op.drop_index(op.f('idx_event_trace_time'), table_name='event_trace')
    op.create_index('idx_event_trace_time', 'event_trace', ['observed_time'], unique=False)
    op.create_index(op.f('ix_event_trace_court_id'), 'event_trace', ['court_id'], unique=False)
    op.alter_column('field_state', 'court_id',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('field_state', 'field_name',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('field_state', 'start_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('field_state', 'last_seen_time',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('matter', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('matter', 'user_id',
               existing_type=sa.UUID(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('matter', 'case_type',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('matter', 'case_number',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('matter', 'court_no',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('matter', 'status',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'active'::text"))
    op.alter_column('matter', 'billing_mode',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'appearance'::text"))
    op.alter_column('matter', 'opened_at',
               existing_type=sa.DATE(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('matter', 'closed_at',
               existing_type=sa.DATE(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('matter', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_constraint(op.f('matter_user_id_case_ref_key'), 'matter', type_='unique')
    op.create_unique_constraint('uq_matter', 'matter', ['user_id', 'case_ref'])
    op.create_foreign_key(None, 'matter', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.alter_column('monitor_state', 'key',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('notification_log', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('notification_log', 'sub_id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=True)
    op.alter_column('notification_log', 'sent_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('notification_log', 'status',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'sent'::text"))
    op.alter_column('phone_otps', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('phone_otps', 'phone',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('phone_otps', 'otp_hash',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('phone_otps', 'expires_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('phone_otps', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('idx_phone_otps_phone'), table_name='phone_otps')
    op.alter_column('subscriptions', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('subscriptions', 'telegram_id',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('subscriptions', 'room_no',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('subscriptions', 'created_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('subscriptions', 'hearing_date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'contact_type',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'telegram'::text"))
    op.alter_column('subscriptions', 'display_name',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'phone',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'alerted_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('tracked_cases', 'id',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('tracked_cases', 'user_id',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('tracked_cases', 'court_no',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('tracked_cases', 'list_date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('tracked_cases', 'added_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('(now())::text'))
    op.alter_column('tracked_cases', 'alerted_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.drop_constraint(op.f('tracked_cases_user_id_case_ref_key'), 'tracked_cases', type_='unique')
    op.create_unique_constraint('uq_tracked_case', 'tracked_cases', ['user_id', 'case_ref'])
    op.create_foreign_key(None, 'tracked_cases', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.drop_column('tracked_cases', 'case_type')
    op.drop_column('tracked_cases', 'case_year')
    op.drop_column('tracked_cases', 'notes')
    op.drop_column('tracked_cases', 'created_at')
    op.drop_column('tracked_cases', 'notify_email')
    op.drop_column('tracked_cases', 'notify_whatsapp')
    op.drop_column('tracked_cases', 'case_number')
    op.alter_column('users', 'id',
               existing_type=sa.UUID(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('gen_random_uuid()'))
    op.alter_column('users', 'phone',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('users', 'email',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('users', 'name',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=True)
    op.alter_column('users', 'role',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'client'::text"))
    op.alter_column('users', 'tier',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'free'::text"))
    op.alter_column('users', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('idx_users_phone'), table_name='users')
    op.alter_column('vc_zoom_link', 'date',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('vc_zoom_link', 'room_no',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    op.alter_column('vc_zoom_link', 'scraped_at',
               existing_type=sa.TEXT(),
               type_=sa.String(),
               existing_nullable=False)
    # ### end Alembic commands ###


def _old_downgrade_unused() -> None:
    op.alter_column('vc_zoom_link', 'scraped_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('vc_zoom_link', 'room_no',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('vc_zoom_link', 'date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.create_index(op.f('idx_users_phone'), 'users', ['phone'], unique=False)
    op.alter_column('users', 'created_at',
               existing_type=sa.String(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('users', 'tier',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text("'free'::text"))
    op.alter_column('users', 'role',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text("'client'::text"))
    op.alter_column('users', 'name',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('users', 'email',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('users', 'phone',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('users', 'id',
               existing_type=sa.String(),
               type_=sa.UUID(),
               existing_nullable=False,
               existing_server_default=sa.text('gen_random_uuid()'))
    op.add_column('tracked_cases', sa.Column('case_number', sa.TEXT(), autoincrement=False, nullable=True))
    op.add_column('tracked_cases', sa.Column('notify_whatsapp', sa.INTEGER(), server_default=sa.text('0'), autoincrement=False, nullable=False))
    op.add_column('tracked_cases', sa.Column('notify_email', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False))
    op.add_column('tracked_cases', sa.Column('created_at', sa.TEXT(), autoincrement=False, nullable=False))
    op.add_column('tracked_cases', sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True))
    op.add_column('tracked_cases', sa.Column('case_year', sa.INTEGER(), autoincrement=False, nullable=True))
    op.add_column('tracked_cases', sa.Column('case_type', sa.TEXT(), autoincrement=False, nullable=True))
    op.drop_constraint(None, 'tracked_cases', type_='foreignkey')
    op.drop_constraint('uq_tracked_case', 'tracked_cases', type_='unique')
    op.create_unique_constraint(op.f('tracked_cases_user_id_case_ref_key'), 'tracked_cases', ['user_id', 'case_ref'], postgresql_nulls_not_distinct=False)
    op.alter_column('tracked_cases', 'alerted_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('tracked_cases', 'added_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text('(now())::text'))
    op.alter_column('tracked_cases', 'list_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('tracked_cases', 'court_no',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('tracked_cases', 'user_id',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('tracked_cases', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('subscriptions', 'alerted_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'phone',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'display_name',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'contact_type',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text("'telegram'::text"))
    op.alter_column('subscriptions', 'hearing_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('subscriptions', 'created_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('subscriptions', 'room_no',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('subscriptions', 'telegram_id',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('subscriptions', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.create_index(op.f('idx_phone_otps_phone'), 'phone_otps', ['phone'], unique=False)
    op.alter_column('phone_otps', 'created_at',
               existing_type=sa.String(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('phone_otps', 'expires_at',
               existing_type=sa.String(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False)
    op.alter_column('phone_otps', 'otp_hash',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('phone_otps', 'phone',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('phone_otps', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('notification_log', 'status',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text("'sent'::text"))
    op.alter_column('notification_log', 'sent_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('notification_log', 'sub_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=True)
    op.alter_column('notification_log', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('monitor_state', 'key',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.drop_constraint(None, 'matter', type_='foreignkey')
    op.drop_constraint('uq_matter', 'matter', type_='unique')
    op.create_unique_constraint(op.f('matter_user_id_case_ref_key'), 'matter', ['user_id', 'case_ref'], postgresql_nulls_not_distinct=False)
    op.alter_column('matter', 'created_at',
               existing_type=sa.String(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('matter', 'closed_at',
               existing_type=sa.String(),
               type_=sa.DATE(),
               existing_nullable=True)
    op.alter_column('matter', 'opened_at',
               existing_type=sa.String(),
               type_=sa.DATE(),
               existing_nullable=True)
    op.alter_column('matter', 'billing_mode',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text("'appearance'::text"))
    op.alter_column('matter', 'status',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False,
               existing_server_default=sa.text("'active'::text"))
    op.alter_column('matter', 'court_no',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('matter', 'case_number',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('matter', 'case_type',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('matter', 'user_id',
               existing_type=sa.String(),
               type_=sa.UUID(),
               existing_nullable=False)
    op.alter_column('matter', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('field_state', 'last_seen_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('field_state', 'start_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('field_state', 'field_name',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('field_state', 'court_id',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.drop_index(op.f('ix_event_trace_court_id'), table_name='event_trace')
    op.drop_index('idx_event_trace_time', table_name='event_trace')
    op.create_index(op.f('idx_event_trace_time'), 'event_trace', [sa.literal_column('observed_time DESC')], unique=False)
    op.drop_index('idx_event_trace_court', table_name='event_trace')
    op.create_index(op.f('idx_event_trace_court'), 'event_trace', ['court_id', sa.literal_column('observed_time DESC')], unique=False)
    op.alter_column('event_trace', 'observed_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('event_trace', 'end_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('event_trace', 'start_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('event_trace', 'field_name',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('event_trace', 'court_id',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('event_trace', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.alter_column('current_state', 'last_seen_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('current_state', 'court_id',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.drop_constraint('uq_causelist_case', 'causelist_case', type_='unique')
    op.create_index(op.f('idx_cc_respondent_trgm'), 'causelist_case', ['respondent'], unique=False, postgresql_ops={'respondent': 'gin_trgm_ops'}, postgresql_using='gin')
    op.create_index(op.f('idx_cc_petitioner_trgm'), 'causelist_case', ['petitioner'], unique=False, postgresql_ops={'petitioner': 'gin_trgm_ops'}, postgresql_using='gin')
    op.create_index(op.f('idx_cc_advocate_trgm'), 'causelist_case', ['advocate'], unique=False, postgresql_ops={'advocate': 'gin_trgm_ops'}, postgresql_using='gin')
    op.create_unique_constraint(op.f('causelist_case_bench_id_serial_no_key'), 'causelist_case', ['bench_id', 'serial_no'], postgresql_nulls_not_distinct=False)
    op.alter_column('causelist_case', 'scraped_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'hearing_type',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'subsection',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'section',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'case_number',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'case_type',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_case', 'court_no',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'list_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'bench_id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False)
    op.alter_column('causelist_case', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.drop_constraint('uq_causelist_bench', 'causelist_bench', type_='unique')
    op.create_unique_constraint(op.f('causelist_bench_unique_source'), 'causelist_bench', ['list_date', 'court_no', 'side', 'list_type'], postgresql_nulls_not_distinct=False)
    op.alter_column('causelist_bench', 'building',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'floor',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'at_time',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'source_id',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'scraped_at',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('causelist_bench', 'jurisdiction',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=True)
    op.alter_column('causelist_bench', 'list_type',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               nullable=True)
    op.alter_column('causelist_bench', 'side',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               nullable=True)
    op.alter_column('causelist_bench', 'court_no',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('causelist_bench', 'list_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('causelist_bench', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.drop_constraint(None, 'case_timeline_events', type_='foreignkey')
    op.alter_column('case_timeline_events', 'created_at',
               existing_type=sa.String(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('case_timeline_events', 'event_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('case_timeline_events', 'event_type',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('case_timeline_events', 'user_id',
               existing_type=sa.String(),
               type_=sa.UUID(),
               existing_nullable=False)
    op.alter_column('case_timeline_events', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.drop_constraint('uq_case_snapshot', 'case_snapshots', type_='unique')
    op.create_unique_constraint(op.f('case_snapshots_case_ref_list_date_key'), 'case_snapshots', ['case_ref', 'list_date'], postgresql_nulls_not_distinct=False)
    op.alter_column('case_snapshots', 'created_at',
               existing_type=sa.String(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('case_snapshots', 'hash',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('case_snapshots', 'list_date',
               existing_type=sa.String(),
               type_=sa.TEXT(),
               existing_nullable=False)
    op.alter_column('case_snapshots', 'id',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_nullable=False,
               autoincrement=True)
    op.create_table('profiles',
    sa.Column('id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('email', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('display_name', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('role', sa.TEXT(), server_default=sa.text("'client'::text"), autoincrement=False, nullable=False),
    sa.Column('tier', sa.TEXT(), server_default=sa.text("'free'::text"), autoincrement=False, nullable=False),
    sa.Column('phone', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('created_at', sa.TEXT(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('profiles_pkey'))
    )
    # ### end Alembic commands ###

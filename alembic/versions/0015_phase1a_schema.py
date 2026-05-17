"""Phase 1A schema additions: new tables + user columns + causelist FTS

Revision ID: 0015_phase1a
Revises: 4558de5b9871
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_phase1a"
down_revision: Union[str, None] = "4558de5b9871"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pg(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # ── Add new columns to users ───────────────────────────────────────────────
    if "users" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        new_user_cols = [
            ("phone_hash", sa.Column("phone_hash", sa.String(64), nullable=True)),
            ("phone_encrypted", sa.Column("phone_encrypted", sa.Text(), nullable=True)),
            ("email_valid", sa.Column("email_valid", sa.Integer(), nullable=False, server_default="1")),
            ("telegram_chat_id", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True)),
            ("telegram_username", sa.Column("telegram_username", sa.String(100), nullable=True)),
            ("preferred_channel", sa.Column("preferred_channel", sa.String(20), nullable=False, server_default="both")),
            ("quiet_hours_start", sa.Column("quiet_hours_start", sa.String(5), nullable=False, server_default="22:00")),
            ("quiet_hours_end", sa.Column("quiet_hours_end", sa.String(5), nullable=False, server_default="07:00")),
            ("max_notifications_per_day", sa.Column("max_notifications_per_day", sa.Integer(), nullable=False, server_default="10")),
            ("unsubscribe_token", sa.Column("unsubscribe_token", sa.String(64), nullable=True)),
            ("last_login_at", sa.Column("last_login_at", sa.String(), nullable=True)),
        ]
        for col_name, col_def in new_user_cols:
            if col_name not in existing_cols:
                op.add_column("users", col_def)

        # Add unique index on phone_hash if column was just added
        existing_indexes = {i["name"] for i in inspector.get_indexes("users")}
        if "phone_hash" not in existing_cols:
            if "ix_users_phone_hash" not in existing_indexes:
                op.create_index("ix_users_phone_hash", "users", ["phone_hash"], unique=True)
        if "unsubscribe_token" not in existing_cols:
            if "ix_users_unsubscribe_token" not in existing_indexes:
                op.create_index("ix_users_unsubscribe_token", "users", ["unsubscribe_token"], unique=True)

    # ── causelist_entries (flat FTS table) ─────────────────────────────────────
    if "causelist_entries" not in existing_tables:
        op.create_table(
            "causelist_entries",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("case_number", sa.String(100), nullable=True),
            sa.Column("serial_number", sa.Integer(), nullable=True),
            sa.Column("court_id", sa.String(50), nullable=True),
            sa.Column("bench_id", sa.String(50), nullable=True),
            sa.Column("judge_name", sa.String(255), nullable=True),
            sa.Column("petitioner", sa.Text(), nullable=True),
            sa.Column("respondent", sa.Text(), nullable=True),
            sa.Column("advocate_petitioner", sa.Text(), nullable=True),
            sa.Column("advocate_respondent", sa.Text(), nullable=True),
            sa.Column("hearing_date", sa.String(10), nullable=True),
            sa.Column("item_number", sa.Integer(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_storage_path", sa.Text(), nullable=True),
            sa.Column("scraped_at", sa.String(), nullable=False),
            sa.Column("parser_version", sa.String(10), nullable=False, server_default="1.0"),
            sa.Column("search_vector", sa.Text(), nullable=True),
        )
        op.create_index("idx_ce_court_date", "causelist_entries", ["court_id", "hearing_date"])
        op.create_index("idx_ce_case_number", "causelist_entries", ["case_number"])

        # Postgres-only: upgrade search_vector to tsvector and add GIN index + trigger
        if _pg(bind):
            op.execute("ALTER TABLE causelist_entries ALTER COLUMN search_vector TYPE tsvector USING NULL::tsvector")
            op.execute("CREATE INDEX idx_ce_fts_gin ON causelist_entries USING gin(search_vector)")
            op.execute("""
                CREATE INDEX idx_ce_trigram ON causelist_entries USING gin(
                    case_number gin_trgm_ops,
                    petitioner gin_trgm_ops
                )
            """ if _has_extension(bind, "pg_trgm") else "SELECT 1")
            op.execute("""
                CREATE TRIGGER causelist_entries_tsvector_update
                BEFORE INSERT OR UPDATE ON causelist_entries
                FOR EACH ROW EXECUTE FUNCTION
                tsvector_update_trigger(
                    search_vector, 'pg_catalog.english',
                    case_number, petitioner, respondent,
                    advocate_petitioner, judge_name
                )
            """)

    # ── vc_links ───────────────────────────────────────────────────────────────
    if "vc_links" not in existing_tables:
        op.create_table(
            "vc_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("court_id", sa.String(50), nullable=False),
            sa.Column("bench_id", sa.String(50), nullable=False),
            sa.Column("room_id", sa.String(100), nullable=True),
            sa.Column("vc_link", sa.Text(), nullable=False),
            sa.Column("verified", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_verified_at", sa.String(), nullable=True),
            sa.Column("source", sa.String(255), nullable=True),
            sa.Column("added_by", sa.String(255), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.UniqueConstraint("court_id", "bench_id", name="uq_vc_links_court_bench"),
        )
        op.create_index("idx_vc_links_court", "vc_links", ["court_id"])
        op.create_index("idx_vc_links_verified", "vc_links", ["verified", "last_verified_at"])

    # ── vc_link_delivery_log ───────────────────────────────────────────────────
    if "vc_link_delivery_log" not in existing_tables:
        op.create_table(
            "vc_link_delivery_log",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("notification_id", sa.String(36), nullable=True),
            sa.Column("case_number", sa.String(100), nullable=True),
            sa.Column("vc_link_sent", sa.Text(), nullable=True),
            sa.Column("matched_court_id", sa.String(50), nullable=True),
            sa.Column("matched_bench", sa.String(50), nullable=True),
            sa.Column("confidence", sa.String(10), nullable=True),
            sa.Column("delivered_at", sa.String(), nullable=False),
        )
        op.create_index("idx_vcdl_case", "vc_link_delivery_log", ["case_number"])
        op.create_index("idx_vcdl_delivered_at", "vc_link_delivery_log", ["delivered_at"])

    # ── display_board_snapshots ────────────────────────────────────────────────
    if "display_board_snapshots" not in existing_tables:
        op.create_table(
            "display_board_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("court_id", sa.String(50), nullable=False),
            sa.Column("bench_id", sa.String(50), nullable=True),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("diff_from_previous", sa.Text(), nullable=True),
            sa.Column("captured_at", sa.String(), nullable=False),
        )
        op.create_index("idx_dbs_court_time", "display_board_snapshots", ["court_id", "captured_at"])

    # ── admin_alerts ───────────────────────────────────────────────────────────
    if "admin_alerts" not in existing_tables:
        op.create_table(
            "admin_alerts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="WARNING"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("resolved", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(), nullable=False),
        )
        op.create_index("idx_admin_alerts_type", "admin_alerts", ["alert_type"])
        op.create_index("idx_admin_alerts_resolved_at", "admin_alerts", ["resolved", "created_at"])

    # ── reconciliation_results ─────────────────────────────────────────────────
    if "reconciliation_results" not in existing_tables:
        op.create_table(
            "reconciliation_results",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("causelist_entry_id", sa.BigInteger(), nullable=True),
            sa.Column("display_board_snapshot_id", sa.String(36), nullable=True),
            sa.Column("confidence", sa.String(10), nullable=False),
            sa.Column("matched_fields", sa.Text(), nullable=True),
            sa.Column("vc_link_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
        )
        op.create_index("idx_recon_confidence", "reconciliation_results", ["confidence"])
        op.create_index("idx_recon_created_at", "reconciliation_results", ["created_at"])


def _has_extension(bind, ext: str) -> bool:
    try:
        result = bind.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = :ext"), {"ext": ext}
        ).fetchone()
        return result is not None
    except Exception:
        return False


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    for table in [
        "reconciliation_results", "admin_alerts",
        "display_board_snapshots", "vc_link_delivery_log",
        "vc_links", "causelist_entries",
    ]:
        if table in existing_tables:
            op.drop_table(table)

    if "users" in existing_tables:
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        drop_cols = [
            "phone_hash", "phone_encrypted", "email_valid",
            "telegram_chat_id", "telegram_username", "preferred_channel",
            "quiet_hours_start", "quiet_hours_end", "max_notifications_per_day",
            "unsubscribe_token", "last_login_at",
        ]
        for col in drop_cols:
            if col in existing_cols:
                op.drop_column("users", col)

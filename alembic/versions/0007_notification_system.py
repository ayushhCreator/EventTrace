"""Add WhatsApp notification system tables and columns

Revision ID: 0007_notification_system
Revises: 6b8b2d2fd5c1
Create Date: 2026-05-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_notification_system"
down_revision: Union[str, None] = "6b8b2d2fd5c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── users: add whatsapp_verified, daily_wa_cap ────────────────────────────
    existing_user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "whatsapp_verified" not in existing_user_cols:
        op.add_column(
            "users",
            sa.Column("whatsapp_verified", sa.Integer(), nullable=False, server_default="0"),
        )
    if "daily_wa_cap" not in existing_user_cols:
        op.add_column(
            "users",
            sa.Column("daily_wa_cap", sa.Integer(), nullable=False, server_default="20"),
        )

    # ── notification_log: add new columns ────────────────────────────────────
    existing_nl_cols = {c["name"] for c in inspector.get_columns("notification_log")}
    nl_additions = [
        ("user_id", sa.Column("user_id", sa.String(), nullable=True)),
        ("case_ref", sa.Column("case_ref", sa.Text(), nullable=True)),
        ("notification_type", sa.Column("notification_type", sa.String(), nullable=True)),
        ("channel", sa.Column("channel", sa.String(), nullable=True)),
        ("message_text", sa.Column("message_text", sa.Text(), nullable=True)),
        ("provider", sa.Column("provider", sa.String(), nullable=True)),
        ("provider_response", sa.Column("provider_response", sa.Text(), nullable=True)),
        ("retry_count", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")),
        ("delivered_at", sa.Column("delivered_at", sa.String(), nullable=True)),
        ("read_at", sa.Column("read_at", sa.String(), nullable=True)),
        ("dedup_key", sa.Column("dedup_key", sa.String(), nullable=True)),
    ]
    for col_name, col_def in nl_additions:
        if col_name not in existing_nl_cols:
            op.add_column("notification_log", col_def)

    # ── whatsapp_otps ─────────────────────────────────────────────────────────
    if "whatsapp_otps" not in existing_tables:
        op.create_table(
            "whatsapp_otps",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("whatsapp_number", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("otp_hash", sa.String(), nullable=False),
            sa.Column("expires_at", sa.String(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(), nullable=False),
        )

    # ── alert_preferences ─────────────────────────────────────────────────────
    if "alert_preferences" not in existing_tables:
        op.create_table(
            "alert_preferences",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("case_ref", sa.Text(), nullable=False),
            sa.Column("trigger_type", sa.String(), nullable=False),
            sa.Column("channel", sa.String(), nullable=False, server_default="whatsapp"),
            sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("quiet_hours_start", sa.Integer(), nullable=True),
            sa.Column("quiet_hours_end", sa.Integer(), nullable=True),
            sa.UniqueConstraint("user_id", "case_ref", "trigger_type", name="uq_alert_pref"),
        )
        op.create_index("idx_alert_pref_user_case", "alert_preferences", ["user_id", "case_ref"])

    # ── notification_queue ────────────────────────────────────────────────────
    if "notification_queue" not in existing_tables:
        op.create_table(
            "notification_queue",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("notification_log_id", sa.BigInteger(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("case_ref", sa.Text(), nullable=True),
            sa.Column("notification_type", sa.String(), nullable=False),
            sa.Column("channel", sa.String(), nullable=False, server_default="whatsapp"),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("scheduled_at", sa.String(), nullable=False),
            sa.Column("locked_until", sa.String(), nullable=True),
            sa.Column("worker_id", sa.String(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        )
        op.create_index("idx_nq_scheduled", "notification_queue", ["scheduled_at"])
        op.create_index("idx_nq_user", "notification_queue", ["user_id"])

    # ── search_log ────────────────────────────────────────────────────────────
    if "search_log" not in existing_tables:
        op.create_table(
            "search_log",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("query_type", sa.String(), nullable=False),
            sa.Column("query_text", sa.Text(), nullable=False),
            sa.Column("result_count", sa.Integer(), nullable=True),
            sa.Column("searched_at", sa.String(), nullable=False),
            sa.Column("court_source", sa.String(), nullable=True),
        )
        op.create_index("idx_search_log_searched_at", "search_log", ["searched_at"])
        op.create_index("idx_search_log_type", "search_log", ["query_type"])

    # ── indexes on notification_log ───────────────────────────────────────────
    try:
        op.create_index("idx_notification_log_user", "notification_log", ["user_id"])
    except Exception:
        pass
    try:
        op.create_index("idx_notification_log_dedup", "notification_log", ["dedup_key"])
    except Exception:
        pass


def downgrade() -> None:
    op.drop_table("search_log")
    op.drop_table("notification_queue")
    op.drop_table("alert_preferences")
    op.drop_table("whatsapp_otps")
    op.drop_column("users", "daily_wa_cap")
    op.drop_column("users", "whatsapp_verified")

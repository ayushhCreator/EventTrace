"""canonical court/judge/advocate tables + join tables

Revision ID: 0013_canonical_entities
Revises: 0012_case_section_key
Create Date: 2026-05-15

Adds canonical entity tables that promote previously denormalized strings
(judges_json on bench, advocate text on case) into FK-linked rows. Unlocks
judge-wise / advocate-wise / court-wise analytics and multi-HC scaling.

- court: master list of high courts (CHD, PHC, DHC, ...). Pre-seeded.
- judge: canonical judge per court. Normalized name as natural dedupe key.
- advocate: canonical advocate. Normalized name + optional bar_enrollment_no.
- causelist_bench_judge: M:N join with order_index (preserves CJ-first order).
- causelist_case_advocate: M:N join with role (PETITIONER / RESPONDENT / UNKNOWN).

New-rows-only strategy: existing judges_json / advocate columns stay populated.
Backfill of historical rows is via a separate manual script (not in this migration).
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_canonical_entities"
down_revision = "0012_case_section_key"
branch_labels = None
depends_on = None


_COURT_SEED = [
    ("CHD",   "Calcutta High Court",           "West Bengal",     "Kolkata"),
    ("PHC",   "Patna High Court",              "Bihar",           "Patna"),
    ("DHC",   "Delhi High Court",              "Delhi",           "New Delhi"),
    ("BHC",   "Bombay High Court",             "Maharashtra",     "Mumbai"),
    ("MHC",   "Madras High Court",             "Tamil Nadu",      "Chennai"),
    ("KHC",   "Karnataka High Court",          "Karnataka",       "Bengaluru"),
    ("AHC",   "Allahabad High Court",          "Uttar Pradesh",   "Prayagraj"),
    ("TSHC",  "Telangana High Court",          "Telangana",       "Hyderabad"),
    ("KEHC",  "Kerala High Court",             "Kerala",          "Kochi"),
    ("GHC",   "Gujarat High Court",            "Gujarat",         "Ahmedabad"),
    ("PHHC",  "Punjab & Haryana High Court",   "Punjab/Haryana",  "Chandigarh"),
    ("RHC",   "Rajasthan High Court",          "Rajasthan",       "Jodhpur"),
    ("MPHC",  "Madhya Pradesh High Court",     "Madhya Pradesh",  "Jabalpur"),
    ("ORHC",  "Orissa High Court",             "Odisha",          "Cuttack"),
    ("GAHC",  "Gauhati High Court",            "Assam",           "Guwahati"),
    ("JHHC",  "Jharkhand High Court",          "Jharkhand",       "Ranchi"),
    ("CGHC",  "Chhattisgarh High Court",       "Chhattisgarh",    "Bilaspur"),
    ("UKHC",  "Uttarakhand High Court",        "Uttarakhand",     "Nainital"),
    ("HPHC",  "Himachal Pradesh High Court",   "Himachal Pradesh","Shimla"),
    ("JKHC",  "J&K and Ladakh High Court",     "J&K/Ladakh",      "Srinagar"),
    ("MEGHC", "Meghalaya High Court",          "Meghalaya",       "Shillong"),
    ("MANHC", "Manipur High Court",            "Manipur",         "Imphal"),
    ("SIKHC", "Sikkim High Court",             "Sikkim",          "Gangtok"),
    ("TRHC",  "Tripura High Court",            "Tripura",         "Agartala"),
    ("APHC",  "Andhra Pradesh High Court",     "Andhra Pradesh",  "Amaravati"),
]


def upgrade() -> None:
    # ── court ────────────────────────────────────────────────────────────────
    op.create_table(
        "court",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("jurisdiction_state", sa.String(), nullable=True),
        sa.Column("seat_city", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False, server_default=sa.text("'2026-05-15T00:00:00Z'")),
    )

    # ── judge ────────────────────────────────────────────────────────────────
    op.create_table(
        "judge",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("court_id", sa.String(), sa.ForeignKey("court.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("designation", sa.String(), nullable=True),  # CHIEF_JUSTICE / JUSTICE / DR_JUSTICE
        sa.Column("first_seen_at", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.String(), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("court_id", "normalized_name", name="uq_judge_court_name"),
    )
    op.create_index("idx_judge_court", "judge", ["court_id"])
    op.create_index("idx_judge_norm", "judge", ["normalized_name"])

    # ── advocate ─────────────────────────────────────────────────────────────
    op.create_table(
        "advocate",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("bar_enrollment_no", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.String(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_advocate_name"),
    )
    op.create_index("idx_advocate_norm", "advocate", ["normalized_name"])
    op.create_index("idx_advocate_bar", "advocate", ["bar_enrollment_no"])

    # ── causelist_bench_judge ────────────────────────────────────────────────
    op.create_table(
        "causelist_bench_judge",
        sa.Column("bench_id", sa.BigInteger(), sa.ForeignKey("causelist_bench.id", ondelete="CASCADE"), nullable=False),
        sa.Column("judge_id", sa.BigInteger(), sa.ForeignKey("judge.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("bench_id", "judge_id", name="pk_bench_judge"),
    )
    op.create_index("idx_bench_judge_bench", "causelist_bench_judge", ["bench_id"])
    op.create_index("idx_bench_judge_judge", "causelist_bench_judge", ["judge_id"])

    # ── causelist_case_advocate ──────────────────────────────────────────────
    op.create_table(
        "causelist_case_advocate",
        sa.Column("case_id", sa.BigInteger(), sa.ForeignKey("causelist_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("advocate_id", sa.BigInteger(), sa.ForeignKey("advocate.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.PrimaryKeyConstraint("case_id", "advocate_id", "role", name="pk_case_advocate"),
    )
    op.create_index("idx_case_advocate_case", "causelist_case_advocate", ["case_id"])
    op.create_index("idx_case_advocate_advocate", "causelist_case_advocate", ["advocate_id"])

    # ── seed court rows ──────────────────────────────────────────────────────
    court_t = sa.table(
        "court",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("jurisdiction_state", sa.String),
        sa.column("seat_city", sa.String),
        sa.column("created_at", sa.String),
    )
    op.bulk_insert(
        court_t,
        [
            {"id": c, "name": n, "jurisdiction_state": s, "seat_city": city,
             "created_at": "2026-05-15T00:00:00Z"}
            for c, n, s, city in _COURT_SEED
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_case_advocate_advocate", "causelist_case_advocate")
    op.drop_index("idx_case_advocate_case", "causelist_case_advocate")
    op.drop_table("causelist_case_advocate")

    op.drop_index("idx_bench_judge_judge", "causelist_bench_judge")
    op.drop_index("idx_bench_judge_bench", "causelist_bench_judge")
    op.drop_table("causelist_bench_judge")

    op.drop_index("idx_advocate_bar", "advocate")
    op.drop_index("idx_advocate_norm", "advocate")
    op.drop_table("advocate")

    op.drop_index("idx_judge_norm", "judge")
    op.drop_index("idx_judge_court", "judge")
    op.drop_table("judge")

    op.drop_table("court")

"""SQLAlchemy declarative models for all EventTrace tables.

These models are the single source of truth for schema. Alembic autogenerates
migrations by diffing these models against the live DB.

Production DB: PostgreSQL. Dev DB: SQLite (for Alembic dry-runs, use SQLite).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class CurrentState(Base):
    __tablename__ = "current_state"

    court_id = Column(String, primary_key=True)
    data_json = Column(Text, nullable=False)
    last_seen_time = Column(String, nullable=False)
    source_court = Column(String, nullable=False, default="CHD")


class FieldState(Base):
    __tablename__ = "field_state"

    court_id = Column(String, nullable=False, primary_key=True)
    field_name = Column(String, nullable=False, primary_key=True)
    value = Column(Text, nullable=True)
    start_time = Column(String, nullable=False)
    last_seen_time = Column(String, nullable=False)
    source_court = Column(String, nullable=False, default="CHD")


class EventTrace(Base):
    __tablename__ = "event_trace"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    court_id = Column(String, nullable=False, index=True)
    field_name = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    observed_time = Column(String, nullable=False)
    source_court = Column(String, nullable=False, default="CHD")

    __table_args__ = (
        Index("idx_event_trace_time", "observed_time"),
        Index("idx_event_trace_court", "court_id", "observed_time"),
        Index("idx_event_trace_source_court", "source_court", "court_id", "observed_time"),
    )


class VcZoomLink(Base):
    __tablename__ = "vc_zoom_link"

    date = Column(String, nullable=False, primary_key=True)
    room_no = Column(String, nullable=False, primary_key=True)
    zoom_url = Column(Text, nullable=False)
    scraped_at = Column(String, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(String, nullable=False)
    room_no = Column(String, nullable=False)
    target_serial = Column(Integer, nullable=False)
    look_ahead = Column(Integer, nullable=False, default=5)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False)
    hearing_date = Column(String, nullable=True)
    contact_type = Column(String, nullable=False, default="telegram")
    last_notified_serial = Column(Integer, nullable=True)
    display_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    alerted_at = Column(String, nullable=True)
    reminder_sent = Column(Integer, nullable=False, default=0)

    notifications = relationship("NotificationLog", back_populates="subscription")


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sub_id = Column(BigInteger, ForeignKey("subscriptions.id"), nullable=True)
    sent_at = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    tracked_case_id = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="sent")

    subscription = relationship("Subscription", back_populates="notifications")


class MonitorState(Base):
    __tablename__ = "monitor_state"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)


class CauselistBench(Base):
    __tablename__ = "causelist_bench"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    list_date = Column(String, nullable=False)
    court_no = Column(String, nullable=False)
    bench_label = Column(Text, nullable=True)
    side = Column(String, nullable=False, default="APPELLATE SIDE")
    list_type = Column(String, nullable=False, default="DAILY")
    judges_json = Column(Text, nullable=False, default="[]")
    not_sitting = Column(Integer, nullable=False, default=0)
    vc_link = Column(Text, nullable=True)
    jurisdiction = Column(String, nullable=True)
    scraped_at = Column(String, nullable=False)
    source_id = Column(String, nullable=True)
    at_time = Column(String, nullable=True)
    floor = Column(String, nullable=True)
    building = Column(String, nullable=True)
    source_court = Column(String, nullable=False, default="CHD")

    cases = relationship("CauselistCase", back_populates="bench", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("list_date", "court_no", "side", "list_type", name="uq_causelist_bench"),
        Index("idx_causelist_bench_date", "list_date"),
        Index("idx_causelist_bench_court", "court_no", "list_date"),
        Index("idx_causelist_bench_source_court", "source_court", "list_date", "court_no"),
    )


class CauselistCase(Base):
    __tablename__ = "causelist_case"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bench_id = Column(BigInteger, ForeignKey("causelist_bench.id", ondelete="CASCADE"), nullable=False)
    list_date = Column(String, nullable=False)
    court_no = Column(String, nullable=False)
    serial_no = Column(Integer, nullable=False)
    case_ref = Column(Text, nullable=True)
    case_type = Column(String, nullable=True)
    case_number = Column(String, nullable=True)
    case_year = Column(Integer, nullable=True)
    petitioner = Column(Text, nullable=True)
    respondent = Column(Text, nullable=True)
    advocate = Column(Text, nullable=True)
    pro_se = Column(Integer, nullable=False, default=0)
    ia_numbers_json = Column(Text, nullable=False, default="[]")
    section = Column(String, nullable=True)
    subsection = Column(String, nullable=True)
    hearing_type = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    scraped_at = Column(String, nullable=False)

    bench = relationship("CauselistBench", back_populates="cases")

    __table_args__ = (
        UniqueConstraint("bench_id", "serial_no", name="uq_causelist_case"),
        Index("idx_causelist_case_ref", "case_ref"),
        Index("idx_causelist_case_date_court", "list_date", "court_no"),
        Index("idx_causelist_case_type_year", "case_type", "case_year"),
        Index("idx_causelist_case_advocate", "advocate"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    phone = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=True)
    name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="client")
    tier = Column(String, nullable=False, default="free")
    verified = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)
    notification_prefs = Column(Text, nullable=True)

    otps = relationship("PhoneOtp", back_populates="user_ref", primaryjoin="User.phone == foreign(PhoneOtp.phone)", viewonly=True)
    tracked_cases = relationship("TrackedCase", back_populates="user", cascade="all, delete-orphan")
    timeline_events = relationship("CaseTimelineEvent", back_populates="user", cascade="all, delete-orphan")
    matters = relationship("Matter", back_populates="user", cascade="all, delete-orphan")


class PhoneOtp(Base):
    __tablename__ = "phone_otps"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    phone = Column(String, nullable=False)
    otp_hash = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    used = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)

    user_ref = relationship("User", primaryjoin="foreign(PhoneOtp.phone) == User.phone", viewonly=True)


class TrackedCase(Base):
    __tablename__ = "tracked_cases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    case_ref = Column(Text, nullable=False)
    court_no = Column(String, nullable=True)
    bench_label = Column(Text, nullable=True)
    judges_json = Column(Text, nullable=True)
    list_date = Column(String, nullable=True)
    serial_no = Column(Integer, nullable=True)
    petitioner = Column(Text, nullable=True)
    respondent = Column(Text, nullable=True)
    alert_active = Column(Integer, nullable=False, default=0)
    alert_serial = Column(Integer, nullable=True)
    look_ahead = Column(Integer, nullable=False, default=5)
    added_at = Column(String, nullable=False)
    alerted_at = Column(String, nullable=True)

    user = relationship("User", back_populates="tracked_cases")

    __table_args__ = (
        UniqueConstraint("user_id", "case_ref", name="uq_tracked_case"),
        Index("idx_tracked_cases_user", "user_id"),
        Index("idx_tracked_cases_ref", "case_ref"),
    )


class CaseSnapshot(Base):
    __tablename__ = "case_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_ref = Column(Text, nullable=False)
    list_date = Column(String, nullable=False)
    data_json = Column(Text, nullable=False)
    hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("case_ref", "list_date", name="uq_case_snapshot"),
        Index("idx_case_snapshots_ref", "case_ref"),
        Index("idx_case_snapshots_date", "list_date"),
    )


class CaseTimelineEvent(Base):
    __tablename__ = "case_timeline_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    case_ref = Column(Text, nullable=False)
    event_type = Column(String, nullable=False)
    event_date = Column(String, nullable=False)
    change_summary = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)

    user = relationship("User", back_populates="timeline_events")

    __table_args__ = (
        Index("idx_cte_user_ref", "user_id", "case_ref"),
        Index("idx_cte_event_date", "event_date"),
    )


class Matter(Base):
    __tablename__ = "matter"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    case_ref = Column(Text, nullable=False)
    case_title = Column(Text, nullable=True)
    case_type = Column(String, nullable=True)
    case_number = Column(String, nullable=True)
    case_year = Column(Integer, nullable=True)
    court_no = Column(String, nullable=True)
    petitioner = Column(Text, nullable=True)
    respondent = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="active")
    billing_mode = Column(String, nullable=False, default="appearance")
    fee_per_appearance = Column(Numeric(12, 2), nullable=True)
    notes = Column(Text, nullable=True)
    opened_at = Column(String, nullable=True)
    closed_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False)

    user = relationship("User", back_populates="matters")

    __table_args__ = (
        UniqueConstraint("user_id", "case_ref", name="uq_matter"),
        Index("idx_matter_user", "user_id"),
        Index("idx_matter_case_ref", "case_ref"),
        Index("idx_matter_status", "user_id", "status"),
    )

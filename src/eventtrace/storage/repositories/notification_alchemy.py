"""SQLAlchemy-based notification repository.

Handles NotificationLog, NotificationQueue, AlertPreference, and SearchLog.
Single implementation for both SQLite and PostgreSQL.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ...common.time import iso, utc_now
from ..models import AlertPreference, NotificationLog, NotificationQueue, SearchLog


def _nl_to_dict(row: NotificationLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "tracked_case_id": row.tracked_case_id,
        "case_ref": row.case_ref,
        "notification_type": row.notification_type,
        "channel": row.channel,
        "message_text": row.message_text,
        "status": row.status,
        "provider": row.provider,
        "provider_response": row.provider_response,
        "retry_count": row.retry_count,
        "sent_at": row.sent_at,
        "delivered_at": row.delivered_at,
        "read_at": row.read_at,
        "dedup_key": row.dedup_key,
        "sub_id": row.sub_id,
    }


def _ap_to_dict(row: AlertPreference) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "case_ref": row.case_ref,
        "trigger_type": row.trigger_type,
        "channel": row.channel,
        "enabled": bool(row.enabled),
        "quiet_hours_start": row.quiet_hours_start,
        "quiet_hours_end": row.quiet_hours_end,
    }


class SQLAlchemyNotificationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ── Notification Log ──────────────────────────────────────────────────────

    def create_notification_log(
        self,
        user_id: str,
        case_ref: str,
        notification_type: str,
        channel: str,
        message_text: str,
        status: str = "queued",
        tracked_case_id: int | None = None,
        provider: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Insert a NotificationLog row. Returns the new id."""
        now = iso(utc_now())
        with Session(self._engine) as session:
            log = NotificationLog(
                user_id=user_id,
                case_ref=case_ref,
                notification_type=notification_type,
                channel=channel,
                message_text=message_text,
                status=status,
                tracked_case_id=tracked_case_id,
                provider=provider,
                dedup_key=dedup_key,
                sent_at=now,
                retry_count=0,
                payload="",
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return int(log.id)

    def update_notification_status(
        self,
        log_id: int,
        status: str,
        provider_response: str | None = None,
        delivered_at: str | None = None,
        read_at: str | None = None,
    ) -> None:
        """Update status, optionally set delivered_at / read_at / provider_response."""
        values: dict = {"status": status}
        if provider_response is not None:
            values["provider_response"] = provider_response
        if delivered_at is not None:
            values["delivered_at"] = delivered_at
        if read_at is not None:
            values["read_at"] = read_at
        with Session(self._engine) as session:
            session.execute(
                update(NotificationLog).where(NotificationLog.id == log_id).values(**values)
            )
            session.commit()

    def get_user_notifications(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        case_ref: str | None = None,
        status: str | None = None,
        unread_only: bool = False,
    ) -> tuple[list[dict], int]:
        """Returns (items, total_count). Order by sent_at DESC."""
        with Session(self._engine) as session:
            base_q = select(NotificationLog).where(NotificationLog.user_id == user_id)
            count_q = select(func.count()).select_from(NotificationLog).where(
                NotificationLog.user_id == user_id
            )
            if case_ref is not None:
                base_q = base_q.where(NotificationLog.case_ref == case_ref)
                count_q = count_q.where(NotificationLog.case_ref == case_ref)
            if unread_only:
                base_q = base_q.where(NotificationLog.status.notin_(["read", "skipped"]))
                count_q = count_q.where(NotificationLog.status.notin_(["read", "skipped"]))
            elif status is not None:
                base_q = base_q.where(NotificationLog.status == status)
                count_q = count_q.where(NotificationLog.status == status)

            total = session.scalar(count_q) or 0
            rows = session.scalars(
                base_q.order_by(NotificationLog.sent_at.desc()).limit(limit).offset(offset)
            ).all()
            return [_nl_to_dict(r) for r in rows], int(total)

    def count_unread_notifications(self, user_id: str) -> int:
        """Count rows where status NOT IN ('read', 'skipped')."""
        with Session(self._engine) as session:
            count = session.scalar(
                select(func.count())
                .select_from(NotificationLog)
                .where(
                    NotificationLog.user_id == user_id,
                    NotificationLog.status.notin_(["read", "skipped"]),
                )
            )
            return int(count or 0)

    def mark_notification_read(self, log_id: int, user_id: str) -> bool:
        """Set status='read', read_at=now. Returns True if row found and owned by user_id."""
        now = iso(utc_now())
        with Session(self._engine) as session:
            result = session.execute(
                update(NotificationLog)
                .where(NotificationLog.id == log_id, NotificationLog.user_id == user_id)
                .values(status="read", read_at=now)
            )
            session.commit()
            return result.rowcount > 0

    def mark_all_notifications_read(self, user_id: str) -> int:
        """Bulk mark all unread as read. Returns count updated."""
        now = iso(utc_now())
        with Session(self._engine) as session:
            result = session.execute(
                update(NotificationLog)
                .where(
                    NotificationLog.user_id == user_id,
                    NotificationLog.status.notin_(["read", "skipped"]),
                )
                .values(status="read", read_at=now)
            )
            session.commit()
            return result.rowcount

    def check_daily_cap(self, user_id: str, channel: str, cap: int) -> bool:
        """Return True if user has sent < cap notifications on channel today (UTC day). False = capped."""
        today = utc_now().date().isoformat()
        with Session(self._engine) as session:
            count = session.scalar(
                select(func.count())
                .select_from(NotificationLog)
                .where(
                    NotificationLog.user_id == user_id,
                    NotificationLog.channel == channel,
                    NotificationLog.sent_at >= today,
                    NotificationLog.status.notin_(["skipped", "failed"]),
                )
            )
            return int(count or 0) < cap

    def check_dedup(self, dedup_key: str, window_hours: int = 1) -> bool:
        """Return True if dedup_key NOT found in notification_log within window_hours. False = duplicate exists."""
        cutoff = iso(utc_now() - timedelta(hours=window_hours))
        with Session(self._engine) as session:
            exists = session.scalar(
                select(func.count())
                .select_from(NotificationLog)
                .where(
                    NotificationLog.dedup_key == dedup_key,
                    NotificationLog.sent_at >= cutoff,
                )
            )
            return int(exists or 0) == 0

    # ── Notification Queue ────────────────────────────────────────────────────

    def enqueue_notification(
        self,
        user_id: str,
        case_ref: str,
        notification_type: str,
        channel: str,
        payload_json: str,
        notification_log_id: int | None = None,
        scheduled_at: str | None = None,
    ) -> int:
        """Insert into notification_queue. scheduled_at defaults to now. Returns queue id."""
        now = iso(utc_now())
        with Session(self._engine) as session:
            item = NotificationQueue(
                user_id=user_id,
                case_ref=case_ref,
                notification_type=notification_type,
                channel=channel,
                payload_json=payload_json,
                notification_log_id=notification_log_id,
                scheduled_at=scheduled_at or now,
                attempt_count=0,
                max_attempts=3,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return int(item.id)

    def claim_queued_notifications(
        self,
        worker_id: str,
        batch_size: int = 20,
        lock_seconds: int = 60,
    ) -> list[dict]:
        """
        SELECT FOR UPDATE SKIP LOCKED on notification_queue (Postgres).
        For SQLite, uses a simple SELECT + UPDATE.
        Returns list of queue row dicts with locked_until set.
        """
        now = iso(utc_now())
        locked_until = iso(utc_now() + timedelta(seconds=lock_seconds))

        with Session(self._engine) as session:
            dialect = session.bind.dialect.name if session.bind else "unknown"

            if dialect == "sqlite":
                # SQLite fallback: no FOR UPDATE SKIP LOCKED
                rows = session.scalars(
                    select(NotificationQueue)
                    .where(
                        NotificationQueue.scheduled_at <= now,
                        (NotificationQueue.locked_until.is_(None))
                        | (NotificationQueue.locked_until < now),
                        NotificationQueue.attempt_count < NotificationQueue.max_attempts,
                    )
                    .order_by(NotificationQueue.scheduled_at)
                    .limit(batch_size)
                ).all()
                ids = [r.id for r in rows]
                if not ids:
                    return []
                session.execute(
                    update(NotificationQueue)
                    .where(NotificationQueue.id.in_(ids))
                    .values(locked_until=locked_until, worker_id=worker_id)
                )
                session.commit()
                claimed = session.scalars(
                    select(NotificationQueue).where(NotificationQueue.id.in_(ids))
                ).all()
                return [_nq_to_dict(r) for r in claimed]
            else:
                # PostgreSQL: FOR UPDATE SKIP LOCKED
                result = session.execute(
                    text("""
                        SELECT id FROM notification_queue
                        WHERE scheduled_at <= :now
                          AND (locked_until IS NULL OR locked_until < :now)
                          AND attempt_count < max_attempts
                        ORDER BY scheduled_at
                        LIMIT :batch_size
                        FOR UPDATE SKIP LOCKED
                    """),
                    {"now": now, "batch_size": batch_size},
                )
                ids = [row[0] for row in result]
                if not ids:
                    return []
                session.execute(
                    update(NotificationQueue)
                    .where(NotificationQueue.id.in_(ids))
                    .values(locked_until=locked_until, worker_id=worker_id)
                )
                session.commit()
                claimed = session.scalars(
                    select(NotificationQueue).where(NotificationQueue.id.in_(ids))
                ).all()
                return [_nq_to_dict(r) for r in claimed]

    def ack_queue_item(self, queue_id: int, success: bool, retry_after_seconds: int = 0) -> None:
        """
        On success: delete the queue row.
        On failure: increment attempt_count, set scheduled_at = now + retry_after_seconds,
                    clear locked_until. If attempt_count >= max_attempts, delete too.
        """
        with Session(self._engine) as session:
            item = session.get(NotificationQueue, queue_id)
            if not item:
                return
            if success:
                session.delete(item)
                session.commit()
                return
            # Failure path
            item.attempt_count += 1
            item.locked_until = None
            item.worker_id = None
            if item.attempt_count >= item.max_attempts:
                session.delete(item)
            else:
                item.scheduled_at = iso(utc_now() + timedelta(seconds=retry_after_seconds))
            session.commit()

    # ── Alert Preferences ─────────────────────────────────────────────────────

    def get_alert_prefs(self, user_id: str, case_ref: str) -> list[dict]:
        """Return all AlertPreference rows for user+case_ref."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(AlertPreference).where(
                    AlertPreference.user_id == user_id,
                    AlertPreference.case_ref == case_ref,
                )
            ).all()
            return [_ap_to_dict(r) for r in rows]

    def upsert_alert_prefs(self, user_id: str, case_ref: str, prefs: list[dict]) -> list[dict]:
        """
        Bulk upsert. Each dict has: trigger_type, channel, enabled, quiet_hours_start, quiet_hours_end.
        Uses INSERT ... ON CONFLICT for Postgres, get+update pattern for SQLite.
        Returns updated list.
        """
        with Session(self._engine) as session:
            dialect = session.bind.dialect.name if session.bind else "unknown"

            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                for pref in prefs:
                    stmt = pg_insert(AlertPreference).values(
                        user_id=user_id,
                        case_ref=case_ref,
                        trigger_type=pref["trigger_type"],
                        channel=pref.get("channel", "whatsapp"),
                        enabled=int(pref.get("enabled", True)),
                        quiet_hours_start=pref.get("quiet_hours_start"),
                        quiet_hours_end=pref.get("quiet_hours_end"),
                    )
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_alert_pref",
                        set_={
                            "channel": stmt.excluded.channel,
                            "enabled": stmt.excluded.enabled,
                            "quiet_hours_start": stmt.excluded.quiet_hours_start,
                            "quiet_hours_end": stmt.excluded.quiet_hours_end,
                        },
                    )
                    session.execute(stmt)
                session.commit()
            else:
                # SQLite fallback: get + update or insert
                for pref in prefs:
                    existing = session.scalar(
                        select(AlertPreference).where(
                            AlertPreference.user_id == user_id,
                            AlertPreference.case_ref == case_ref,
                            AlertPreference.trigger_type == pref["trigger_type"],
                        )
                    )
                    if existing:
                        existing.channel = pref.get("channel", existing.channel)
                        existing.enabled = int(pref.get("enabled", existing.enabled))
                        existing.quiet_hours_start = pref.get(
                            "quiet_hours_start", existing.quiet_hours_start
                        )
                        existing.quiet_hours_end = pref.get(
                            "quiet_hours_end", existing.quiet_hours_end
                        )
                    else:
                        session.add(
                            AlertPreference(
                                user_id=user_id,
                                case_ref=case_ref,
                                trigger_type=pref["trigger_type"],
                                channel=pref.get("channel", "whatsapp"),
                                enabled=int(pref.get("enabled", True)),
                                quiet_hours_start=pref.get("quiet_hours_start"),
                                quiet_hours_end=pref.get("quiet_hours_end"),
                            )
                        )
                session.commit()

        return self.get_alert_prefs(user_id, case_ref)

    def get_alert_pref(self, user_id: str, case_ref: str, trigger_type: str) -> dict | None:
        """Get single pref row."""
        with Session(self._engine) as session:
            row = session.scalar(
                select(AlertPreference).where(
                    AlertPreference.user_id == user_id,
                    AlertPreference.case_ref == case_ref,
                    AlertPreference.trigger_type == trigger_type,
                )
            )
            return _ap_to_dict(row) if row else None

    def upsert_single_alert_pref(
        self,
        user_id: str,
        case_ref: str,
        trigger_type: str,
        channel: str | None = None,
        enabled: bool | None = None,
        quiet_hours_start: int | None = None,
        quiet_hours_end: int | None = None,
    ) -> dict:
        """Upsert single pref row. Returns updated dict."""
        with Session(self._engine) as session:
            dialect = session.bind.dialect.name if session.bind else "unknown"

            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                insert_vals = {
                    "user_id": user_id,
                    "case_ref": case_ref,
                    "trigger_type": trigger_type,
                    "channel": channel or "whatsapp",
                    "enabled": int(enabled) if enabled is not None else 1,
                    "quiet_hours_start": quiet_hours_start,
                    "quiet_hours_end": quiet_hours_end,
                }
                update_vals: dict = {}
                if channel is not None:
                    update_vals["channel"] = channel
                if enabled is not None:
                    update_vals["enabled"] = int(enabled)
                if quiet_hours_start is not None:
                    update_vals["quiet_hours_start"] = quiet_hours_start
                if quiet_hours_end is not None:
                    update_vals["quiet_hours_end"] = quiet_hours_end

                stmt = pg_insert(AlertPreference).values(**insert_vals)
                if update_vals:
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_alert_pref", set_=update_vals
                    )
                else:
                    stmt = stmt.on_conflict_do_nothing(constraint="uq_alert_pref")
                session.execute(stmt)
                session.commit()
            else:
                existing = session.scalar(
                    select(AlertPreference).where(
                        AlertPreference.user_id == user_id,
                        AlertPreference.case_ref == case_ref,
                        AlertPreference.trigger_type == trigger_type,
                    )
                )
                if existing:
                    if channel is not None:
                        existing.channel = channel
                    if enabled is not None:
                        existing.enabled = int(enabled)
                    if quiet_hours_start is not None:
                        existing.quiet_hours_start = quiet_hours_start
                    if quiet_hours_end is not None:
                        existing.quiet_hours_end = quiet_hours_end
                else:
                    session.add(
                        AlertPreference(
                            user_id=user_id,
                            case_ref=case_ref,
                            trigger_type=trigger_type,
                            channel=channel or "whatsapp",
                            enabled=int(enabled) if enabled is not None else 1,
                            quiet_hours_start=quiet_hours_start,
                            quiet_hours_end=quiet_hours_end,
                        )
                    )
                session.commit()

        result = self.get_alert_pref(user_id, case_ref, trigger_type)
        # Should always be found after upsert
        return result or {}

    def get_causelist_alert_status(self, user_id: str, case_ref: str) -> bool:
        """Return True if user has an active case_in_causelist alert pref."""
        row = self.get_alert_pref(user_id, case_ref, "case_in_causelist")
        if row is None:
            return False
        return bool(row.get("enabled", 0))

    # ── Search Log ────────────────────────────────────────────────────────────

    def log_search(
        self,
        query_type: str,
        query_text: str,
        result_count: int | None = None,
        user_id: str | None = None,
        court_source: str | None = None,
    ) -> None:
        """Insert a SearchLog row."""
        now = iso(utc_now())
        with Session(self._engine) as session:
            session.add(
                SearchLog(
                    user_id=user_id,
                    query_type=query_type,
                    query_text=query_text,
                    result_count=result_count,
                    searched_at=now,
                    court_source=court_source,
                )
            )
            session.commit()


    # ── Analytics ─────────────────────────────────────────────────────────────

    def get_notification_stats(self, days: int = 7) -> dict:
        """Aggregate notification_log by status, channel, notification_type for last N days."""
        since = iso(utc_now() - timedelta(days=days))
        with Session(self._engine) as session:
            rows = session.execute(
                text(
                    "SELECT status, channel, notification_type, COUNT(*) AS cnt "
                    "FROM notification_log "
                    "WHERE sent_at >= :since "
                    "GROUP BY status, channel, notification_type "
                    "ORDER BY cnt DESC"
                ),
                {"since": since},
            ).fetchall()
        by_status: dict[str, int] = {}
        by_channel: dict[str, int] = {}
        by_trigger: dict[str, int] = {}
        breakdown = []
        for r in rows:
            status, channel, ntype, cnt = r
            by_status[status] = by_status.get(status, 0) + cnt
            by_channel[channel] = by_channel.get(channel, 0) + cnt
            by_trigger[ntype] = by_trigger.get(ntype, 0) + cnt
            breakdown.append({"status": status, "channel": channel, "trigger_type": ntype, "count": cnt})
        return {
            "days": days,
            "by_status": by_status,
            "by_channel": by_channel,
            "by_trigger": by_trigger,
            "breakdown": breakdown,
        }

    def get_top_searches(self, limit: int = 20) -> list[dict]:
        """Top query_text entries from search_log by frequency."""
        with Session(self._engine) as session:
            rows = session.execute(
                text(
                    "SELECT query_type, query_text, COUNT(*) AS cnt "
                    "FROM search_log "
                    "GROUP BY query_type, query_text "
                    "ORDER BY cnt DESC "
                    "LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return [{"query_type": r[0], "query_text": r[1], "count": r[2]} for r in rows]

    def find_notification_log_by_provider_id(self, provider_id: str) -> dict | None:
        """Lookup notification_log row whose provider_response JSON contains the given message ID."""
        with Session(self._engine) as session:
            row = session.scalar(
                select(NotificationLog)
                .where(NotificationLog.provider_response.contains(provider_id))
                .order_by(NotificationLog.sent_at.desc())
                .limit(1)
            )
            return _nl_to_dict(row) if row else None


def _nq_to_dict(row: NotificationQueue) -> dict:
    return {
        "id": row.id,
        "notification_log_id": row.notification_log_id,
        "user_id": row.user_id,
        "case_ref": row.case_ref,
        "notification_type": row.notification_type,
        "channel": row.channel,
        "payload_json": row.payload_json,
        "scheduled_at": row.scheduled_at,
        "locked_until": row.locked_until,
        "worker_id": row.worker_id,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
    }

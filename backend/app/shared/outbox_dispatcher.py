from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.models.outbox import OutboxEvent
from app.shared.events import DomainEvent, EventBus

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: SessionFactory,
        event_bus: EventBus,
        *,
        max_attempts: int = 8,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 300,
        lease_seconds: int = 60,
    ) -> None:
        if max_attempts < 1 or base_delay_seconds < 1 or max_delay_seconds < 1 or lease_seconds < 1:
            raise ValueError("Outbox retry and lease settings must be positive.")
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._lease_seconds = lease_seconds

    def dispatch_pending(self, *, limit: int = 100, now: datetime | None = None) -> dict[str, int]:
        if limit < 1:
            raise ValueError("limit must be positive.")
        counts = {"processed": 0, "retried": 0, "failed": 0}
        current_time = _aware(now or datetime.now(timezone.utc))
        for _ in range(limit):
            claimed = self._claim(current_time)
            if claimed is None:
                break
            event, lock_token = claimed
            try:
                if not self._event_bus.has_handlers(event.event_name):
                    raise LookupError(f"No handler registered for {event.event_name}.")
                self._event_bus.dispatch(event)
            except Exception as exc:
                logger.error(
                    "Outbox handler failed event_id=%s event_name=%s error_type=%s",
                    event.event_id,
                    event.event_name,
                    type(exc).__name__,
                )
                outcome = self._record_failure(event.event_id, lock_token, exc, current_time)
                counts[outcome] += 1
            else:
                if self._record_success(event.event_id, lock_token, current_time):
                    counts["processed"] += 1
        return counts

    def _claim(self, now: datetime) -> tuple[DomainEvent, str] | None:
        with self._session_factory() as db:
            candidate = db.scalar(
                select(OutboxEvent)
                .where(
                    or_(
                        and_(
                            OutboxEvent.status == "PENDING",
                            OutboxEvent.next_attempt_at <= now,
                        ),
                        and_(
                            OutboxEvent.status == "PROCESSING",
                            OutboxEvent.locked_until <= now,
                        ),
                    )
                )
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if candidate is None:
                return None
            lock_token = str(uuid4())
            candidate.status = "PROCESSING"
            candidate.lock_token = lock_token
            candidate.locked_until = now + timedelta(seconds=self._lease_seconds)
            db.commit()
            return (
                DomainEvent(
                    event_id=candidate.event_id,
                    event_name=candidate.event_name,
                    payload=candidate.payload,
                    occurred_at=_aware(candidate.created_at),
                ),
                lock_token,
            )

    def _record_success(self, event_id: str, lock_token: str, now: datetime) -> bool:
        with self._session_factory() as db:
            result = db.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.event_id == event_id,
                    OutboxEvent.status == "PROCESSING",
                    OutboxEvent.lock_token == lock_token,
                )
                .values(
                    status="PROCESSED",
                    error=None,
                    lock_token=None,
                    locked_until=None,
                    updated_at=now,
                )
            )
            db.commit()
            return result.rowcount == 1

    def _record_failure(
        self,
        event_id: str,
        lock_token: str,
        exc: Exception,
        now: datetime,
    ) -> str:
        with self._session_factory() as db:
            record = db.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.event_id == event_id,
                    OutboxEvent.status == "PROCESSING",
                    OutboxEvent.lock_token == lock_token,
                )
            )
            if record is None:
                return "retried"
            attempts = record.attempts + 1
            failed = attempts >= self._max_attempts
            delay = min(
                self._base_delay_seconds * (2 ** max(0, attempts - 1)),
                self._max_delay_seconds,
            )
            record.attempts = attempts
            record.error = type(exc).__name__[:200]
            record.last_error_at = now
            record.status = "FAILED" if failed else "PENDING"
            record.next_attempt_at = now if failed else now + timedelta(seconds=delay)
            record.lock_token = None
            record.locked_until = None
            record.updated_at = now
            db.commit()
            return "failed" if failed else "retried"


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

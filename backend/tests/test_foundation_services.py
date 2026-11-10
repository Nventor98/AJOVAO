from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.config import settings
from app.db.base import Base
from app.models.outbox import OutboxEvent
from app.shared.events import DomainEvent, EventBus, emit
from app.shared.outbox_dispatcher import OutboxDispatcher
from app.shared.rate_limit import RateLimiter, client_ip, rate_limit_dependency


class FakeRedis:
    def __init__(self, result: list[int] | Exception) -> None:
        self.result = result
        self.call: tuple[object, ...] | None = None

    def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> list[int]:
        self.call = (script, numkeys, *keys_and_args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_rate_limiter_uses_atomic_redis_sliding_window_and_hashes_key() -> None:
    redis = FakeRedis([0, 17])
    limiter = RateLimiter(redis_client=redis)

    assert limiter.allow("login:+2348012345678", requests_per_minute=5) == (False, 17)
    assert redis.call is not None
    script, key_count, redis_key, window, limit, request_id = redis.call
    assert "ZREMRANGEBYSCORE" in str(script)
    assert key_count == 1
    assert str(redis_key).startswith("naijalife:rate-limit:")
    assert "+2348012345678" not in str(redis_key)
    assert window == 60_000
    assert limit == 5
    assert len(str(request_id)) == 36


def test_rate_limiter_fails_closed_when_redis_is_unavailable() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    limiter = RateLimiter(redis_client=FakeRedis(RedisConnectionError("offline")))
    with pytest.raises(HTTPException) as error:
        limiter.allow("login:127.0.0.1")
    assert error.value.status_code == 503


def test_forwarded_ip_is_used_only_for_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", ["10.0.0.0/8"])

    assert client_ip(_request("198.51.100.10", "203.0.113.8")) == "198.51.100.10"
    assert client_ip(_request("10.0.0.4", "203.0.113.8, 10.0.0.3")) == "203.0.113.8"
    assert client_ip(_request("10.0.0.4", "not-an-ip")) == "10.0.0.4"


def test_rate_limit_dependency_returns_retry_after() -> None:
    class DenyAllLimiter:
        def allow(self, _key: str, *, requests_per_minute: int | None = None) -> tuple[bool, int]:
            return False, 23

    enforce = rate_limit_dependency("test-scope", 3)
    with pytest.raises(HTTPException) as error:
        enforce(_request("192.0.2.1"), DenyAllLimiter())
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "23"}


def test_emit_is_atomic_with_the_callers_transaction(session_factory) -> None:
    event = DomainEvent(event_name="test.created", payload={"value": 1})
    with session_factory() as db:
        record = emit(db, event)
        assert record.event_id == event.event_id
        db.rollback()
    with session_factory() as db:
        assert db.scalar(select(OutboxEvent)) is None

    with session_factory() as db:
        emit(db, event)
        db.commit()
    with session_factory() as db:
        stored = db.scalar(select(OutboxEvent))
        assert stored is not None
        assert stored.event_id == event.event_id
        assert stored.status == "PENDING"


def test_dispatcher_processes_pending_events_and_publishes_event_id(session_factory) -> None:
    bus = EventBus()
    seen: list[DomainEvent] = []
    bus.register("test.created", seen.append)
    with session_factory() as db:
        emit(db, DomainEvent(event_name="test.created", payload={"key": "value"}))
        db.commit()
    dispatcher = OutboxDispatcher(session_factory, bus)

    assert dispatcher.dispatch_pending() == {"processed": 1, "retried": 0, "failed": 0}
    assert len(seen) == 1
    assert seen[0].event_name == "test.created"
    with session_factory() as db:
        stored = db.scalar(select(OutboxEvent))
        assert stored is not None
        assert stored.status == "PROCESSED"


def test_dispatcher_retries_with_backoff_and_parks_repeated_failures(session_factory) -> None:
    bus = EventBus()

    def fail(_event: DomainEvent) -> None:
        raise RuntimeError("sensitive exception detail")

    bus.register("test.failing", fail)
    with session_factory() as db:
        emit(db, DomainEvent(event_name="test.failing"))
        db.commit()
    now = datetime.now(timezone.utc)
    dispatcher = OutboxDispatcher(
        session_factory,
        bus,
        max_attempts=2,
        base_delay_seconds=3,
        max_delay_seconds=10,
    )

    assert dispatcher.dispatch_pending(now=now) == {"processed": 0, "retried": 1, "failed": 0}
    with session_factory() as db:
        stored = db.scalar(select(OutboxEvent))
        assert stored is not None
        assert stored.status == "PENDING"
        assert stored.attempts == 1
        assert stored.error == "RuntimeError"
        assert stored.next_attempt_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=3)
    assert dispatcher.dispatch_pending(now=now) == {"processed": 0, "retried": 0, "failed": 0}
    assert dispatcher.dispatch_pending(now=now + timedelta(seconds=3)) == {
        "processed": 0,
        "retried": 0,
        "failed": 1,
    }
    with session_factory() as db:
        stored = db.scalar(select(OutboxEvent))
        assert stored is not None
        assert stored.status == "FAILED"
        assert stored.attempts == 2

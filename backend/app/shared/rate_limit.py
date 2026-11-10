from __future__ import annotations

from hashlib import sha256
import ipaddress
from typing import Protocol
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


class RedisScriptClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> list[int]: ...


_SLIDING_WINDOW_SCRIPT = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry = math.ceil((tonumber(oldest[2]) + window - now) / 1000)
    return {0, math.max(1, retry)}
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


class RateLimiter:
    def __init__(
        self,
        *,
        requests_per_minute: int = 60,
        redis_client: RedisScriptClient | None = None,
        key_prefix: str = "naijalife:rate-limit",
    ) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be positive.")
        self.requests_per_minute = requests_per_minute
        self._redis = (
            redis_client
            if redis_client is not None
            else get_redis_client()
        )
        self._key_prefix = key_prefix

    def allow(self, key: str, *, requests_per_minute: int | None = None) -> tuple[bool, int]:
        limit = requests_per_minute or self.requests_per_minute
        if limit < 1:
            raise ValueError("requests_per_minute must be positive.")
        digest = sha256(key.encode("utf-8")).hexdigest()
        try:
            result = self._redis.eval(
                _SLIDING_WINDOW_SCRIPT,
                1,
                f"{self._key_prefix}:{digest}",
                60_000,
                limit,
                str(uuid4()),
            )
        except RedisError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limiting service is unavailable.",
                headers={"Retry-After": "1"},
            ) from exc
        return bool(int(result[0])), int(result[1])


_rate_limiter: RateLimiter | None = None
_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis_client


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(redis_client=get_redis_client())
    return _rate_limiter


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client is not None else None
    if peer is None:
        return "unknown"
    try:
        peer_address = _parse_ip(peer)
    except ValueError:
        return peer
    if not _is_trusted(peer_address):
        return str(peer_address)

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return str(peer_address)
    try:
        chain = [_parse_ip(value.strip()) for value in forwarded.split(",")]
    except ValueError:
        return str(peer_address)
    for address in reversed(chain):
        if not _is_trusted(address):
            return str(address)
    return str(peer_address)


def _parse_ip(value: str):
    return ipaddress.ip_address(value)


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(address in ipaddress.ip_network(proxy, strict=False) for proxy in settings.trusted_proxies)


def rate_limit_dependency(scope: str, requests_per_minute: int):
    def enforce(
        request: Request,
        limiter: RateLimiter = Depends(get_rate_limiter),
    ) -> None:
        key = f"{scope}:{client_ip(request)}"
        allowed, retry_after = limiter.allow(key, requests_per_minute=requests_per_minute)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests.",
                headers={"Retry-After": str(retry_after)},
            )

    return enforce

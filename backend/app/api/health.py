from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.shared.rate_limit import get_redis_client
from app.shared.responses import ok

router = APIRouter(prefix="/api/v1", tags=["health"])
Db = Annotated[Session, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis_client)]


@router.get("/health")
def health_check() -> dict:
    return ok({
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
    })


@router.get("/ready")
def readiness_check(db: Db, redis: RedisClient) -> dict:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready.",
        ) from exc
    try:
        redis.ping()
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is not ready.",
        ) from exc
    return ok({
        "status": "ready",
        "database": "ready",
        "redis": "ready",
        "app": settings.app_name,
    })

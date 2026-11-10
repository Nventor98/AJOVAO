from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record_audit(
    db: Session,
    *,
    action: str,
    details: dict[str, Any] | None = None,
    actor_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    message: str | None = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        details=details or {},
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
    )
    db.add(log)
    return log

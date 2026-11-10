"""Shared backend utilities."""

from .events import DomainEvent, EventNames, event_bus, emit
from .outbox_dispatcher import OutboxDispatcher
from .pagination import Pagination, paginate, paginated_ok
from .permissions import Permission, Role, ensure_owner_or_permission, require_permissions, require_roles
from .rate_limit import RateLimiter
from .responses import SuccessEnvelope, ValidationError, api_error, ok

__all__ = [
    "SuccessEnvelope",
    "ValidationError",
    "api_error",
    "ok",
    "Pagination",
    "paginate",
    "paginated_ok",
    "Role",
    "Permission",
    "require_roles",
    "require_permissions",
    "ensure_owner_or_permission",
    "DomainEvent",
    "EventNames",
    "event_bus",
    "emit",
    "OutboxDispatcher",
    "RateLimiter",
]

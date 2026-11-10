from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class SuccessEnvelope:
    success: bool = True
    data: Any = None
    meta: dict[str, Any] = field(default_factory=dict)


def ok(data: Any = None, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"success": True, "data": data, "meta": meta or {}}


class APIError(Exception):
    def __init__(self, code: str, message: str, details: list[str] | None = None):
        self.code = code
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class ValidationError(APIError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__("VALIDATION_ERROR", message, details)


class UnauthorizedError(APIError):
    def __init__(self, message: str = "Authentication required."):
        super().__init__("UNAUTHORIZED", message)


class ForbiddenError(APIError):
    def __init__(self, message: str = "Access denied."):
        super().__init__("FORBIDDEN", message)


class NotFoundError(APIError):
    def __init__(self, message: str):
        super().__init__("NOT_FOUND", message)


def api_error(code: str, message: str, details: list[str] | None = None) -> dict[str, Any]:
    return APIError(code, message, details).to_dict()

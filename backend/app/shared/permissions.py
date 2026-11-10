from __future__ import annotations

from enum import Enum
from typing import Iterable

from fastapi import HTTPException, status


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"
    COMMUNITY_ADMIN = "community_admin"
    COMMUNITY_AGENT = "community_agent"
    FARMER = "farmer"
    SUPPLIER = "supplier"
    STAFF = "staff"


class Permission(str, Enum):
    READ_OWN = "read:own"
    WRITE_OWN = "write:own"
    READ_USERS = "read:users"
    WRITE_USERS = "write:users"
    READ_COMMUNITIES = "read:communities"
    WRITE_COMMUNITIES = "write:communities"
    READ_ORDERS = "read:orders"
    WRITE_ORDERS = "write:orders"
    READ_SUPPLIERS = "read:suppliers"
    WRITE_SUPPLIERS = "write:suppliers"
    READ_FARMERS = "read:farmers"
    WRITE_FARMERS = "write:farmers"
    READ_SOURCING = "read:sourcing"
    WRITE_SOURCING = "write:sourcing"
    READ_SCORECARDS = "read:scorecards"
    WRITE_SCORECARDS = "write:scorecards"
    READ_PRICING = "read:pricing"
    WRITE_PRICING = "write:pricing"
    READ_PRODUCTS = "read:products"
    WRITE_PRODUCTS = "write:products"
    VERIFY_SUPPLIERS = "verify:suppliers"
    PUBLISH_PRICE_INDEX = "publish:price_index"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.USER: {Permission.READ_OWN, Permission.WRITE_OWN},
    Role.COMMUNITY_ADMIN: {Permission.READ_COMMUNITIES, Permission.WRITE_COMMUNITIES, Permission.READ_ORDERS, Permission.WRITE_ORDERS},
    Role.COMMUNITY_AGENT: {Permission.READ_OWN, Permission.WRITE_OWN, Permission.READ_ORDERS},
    Role.FARMER: {Permission.READ_FARMERS, Permission.WRITE_FARMERS, Permission.READ_OWN, Permission.WRITE_OWN},
    Role.SUPPLIER: {
        Permission.READ_SUPPLIERS,
        Permission.WRITE_SUPPLIERS,
        Permission.READ_PRICING,
        Permission.READ_PRODUCTS,
    },
    Role.STAFF: {Permission.READ_USERS, Permission.WRITE_USERS, Permission.READ_ORDERS},
}


def _normalise_roles(value: Iterable[str] | str | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def _normalise_permissions(value: Iterable[str] | str | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(v) for v in value}


def require_roles(current_user: object, *roles: str | Role) -> None:
    user_roles = _normalise_roles(getattr(current_user, "roles", []))
    allowed = {(role.value if isinstance(role, Role) else str(role)).lower() for role in roles}
    if not user_roles.intersection(allowed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role access denied")


def require_permissions(current_user: object, *permissions: str | Permission) -> None:
    user_permissions = _normalise_permissions(getattr(current_user, "permissions", []))
    allowed = {
        (permission.value if isinstance(permission, Permission) else str(permission)).lower()
        for permission in permissions
    }
    if not user_permissions.intersection(allowed):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")


def ensure_owner_or_permission(current_user: object, owner_id: str | None, *permissions: str | Permission) -> None:
    if owner_id and getattr(current_user, "user_id", None) == owner_id:
        return
    require_permissions(current_user, *permissions)

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.auth import resolve_access_token
from app.db.session import get_db


class CurrentUser(BaseModel):
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    is_authenticated: bool = True


def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    db: Session = Depends(get_db),
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = resolve_access_token(db, token)
    return CurrentUser(
        user_id=user.id,
        email=user.email,
        roles=user.roles or [],
        permissions=user.permissions or [],
    )


CurrentUserDependency = Annotated[CurrentUser, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]

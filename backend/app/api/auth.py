from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps.auth import CurrentUserDependency
from app.db.session import get_db
from app.models.user import User
from app.core.config import settings
from app.services.auth import (
    VerificationSender,
    create_access_token,
    create_phone_verification,
    hash_password,
    normalize_phone,
    send_verification_code,
    verify_password,
    verify_phone_code,
)
from app.shared.audit import record_audit
from app.shared.rate_limit import rate_limit_dependency
from app.shared.responses import ok

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
profile_router = APIRouter(prefix="/api/v1/users", tags=["users"])
Db = Annotated[Session, Depends(get_db)]


class RegisterRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    password: SecretStr = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    preferred_language: str = Field(default="en", min_length=2, max_length=12)


class VerifyPhoneRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    code: str = Field(pattern=r"^\d{6}$")


class LoginRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    password: SecretStr = Field(min_length=1, max_length=128)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)
    preferred_language: str | None = Field(default=None, min_length=2, max_length=12)


def get_verification_sender() -> VerificationSender:
    return send_verification_code


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "phone": user.phone,
        "full_name": user.full_name,
        "preferred_language": user.preferred_language,
        "roles": user.roles,
        "phone_verified": user.phone_verified_at is not None,
    }


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_dependency("auth-register", 5))],
)
def register(
    payload: RegisterRequest,
    db: Db,
    sender: Annotated[VerificationSender, Depends(get_verification_sender)],
) -> dict:
    phone = normalize_phone(payload.phone)
    existing = db.scalar(select(User).where(User.phone == phone))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number is already registered.")
    user = User(
        phone=phone,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password.get_secret_value()),
        preferred_language=payload.preferred_language,
        roles=["user"],
        permissions=["read:own", "write:own"],
    )
    try:
        db.add(user)
        db.flush()
        create_phone_verification(db, user, sender)
        record_audit(db, action="auth.registration_requested", actor_id=user.id, entity_type="user", entity_id=user.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number is already registered.") from exc
    return ok({"user_id": user.id, "phone_verification_required": True})


@router.post(
    "/verify-phone",
    dependencies=[Depends(rate_limit_dependency("auth-verify-phone", 10))],
)
def verify_phone(payload: VerifyPhoneRequest, db: Db) -> dict:
    phone = normalize_phone(payload.phone)
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None or user.phone_verified_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone verification could not be completed.")
    if not verify_phone_code(db, user, payload.code):
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone verification could not be completed.")
    record_audit(db, action="auth.phone_verified", actor_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()
    return ok({"verified": True})


@router.post("/login", dependencies=[Depends(rate_limit_dependency("auth-login", 10))])
def login(payload: LoginRequest, db: Db) -> dict:
    phone = normalize_phone(payload.phone)
    user = db.scalar(select(User).where(User.phone == phone))
    if (
        user is None
        or not verify_password(payload.password.get_secret_value(), user.password_hash)
        or not user.is_active
        or user.phone_verified_at is None
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone number or password.")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    token = create_access_token(user)
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.access_token_ttl_minutes * 60,
            "user": user_payload(user),
        }
    )


@router.get("/me")
def get_profile(current_user: CurrentUserDependency, db: Db) -> dict:
    user = db.get(User, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return ok(user_payload(user))


@profile_router.get("/me")
def get_current_profile(current_user: CurrentUserDependency, db: Db) -> dict:
    return get_profile(current_user, db)


@profile_router.patch("/me")
def update_profile(payload: ProfileUpdate, current_user: CurrentUserDependency, db: Db) -> dict:
    user = db.get(User, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    record_audit(
        db,
        action="user.profile_updated",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return ok(user_payload(user))

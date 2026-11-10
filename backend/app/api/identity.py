from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps.auth import CurrentUserDependency
from app.db.types import point_wkt
from app.db.session import get_db
from app.models.identity import (
    Address,
    AgentCommunityAssignment,
    AgentConsent,
    Community,
    CommunityAgent,
    CommunityMembership,
    CollectionPoint,
)
from app.models.user import User
from app.services.identity import ensure_agent_consent
from app.shared.audit import record_audit
from app.shared.permissions import Permission, Role, require_roles
from app.shared.responses import ok

router = APIRouter(prefix="/api/v1", tags=["identity and communities"])
Db = Annotated[Session, Depends(get_db)]
CommunityType = Literal["estate", "market", "faith_group", "cooperative", "workplace", "union", "other"]
ConsentScope = Literal["orders:place", "orders:amend", "farmer:register"]


class CommunityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    community_type: CommunityType
    description: str | None = Field(default=None, max_length=2000)
    area: str | None = Field(default=None, max_length=160)
    country_code: str = Field(default="NG", pattern=r"^[A-Z]{2}$")


class AddressCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    address_line: str = Field(min_length=3, max_length=255)
    area: str = Field(min_length=1, max_length=160)
    city: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=120)
    country_code: str = Field(default="NG", pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "AddressCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return self


class AddressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=80)
    address_line: str | None = Field(default=None, min_length=3, max_length=255)
    area: str | None = Field(default=None, min_length=1, max_length=160)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    state: str | None = Field(default=None, min_length=1, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "AddressUpdate":
        if ("latitude" in self.model_fields_set) != ("longitude" in self.model_fields_set):
            raise ValueError("Latitude and longitude must be updated together.")
        return self


class CollectionPointCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address_line: str = Field(min_length=3, max_length=255)
    operating_hours: str | None = Field(default=None, max_length=255)
    responsible_person: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "CollectionPointCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return self


class AgentAssignment(BaseModel):
    agent_id: str = Field(min_length=1, max_length=36)


class ConsentCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=36)
    scopes: list[ConsentScope] = Field(min_length=1)
    expires_at: datetime

    @model_validator(mode="after")
    def expiration_is_timezone_aware_and_future(self) -> "ConsentCreate":
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Consent expiry must include a timezone.")
        if self.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Consent expiry must be in the future.")
        return self


class FarmerRegistrationAssist(BaseModel):
    consent_id: str = Field(min_length=1, max_length=36)


class AgentApprovalRequest(BaseModel):
    identity_verified: bool


def _address_payload(address: Address) -> dict:
    return {
        "id": address.id,
        "label": address.label,
        "address_line": address.address_line,
        "area": address.area,
        "city": address.city,
        "state": address.state,
        "country_code": address.country_code,
        "latitude": address.latitude,
        "longitude": address.longitude,
    }


def _community_payload(community: Community, membership: CommunityMembership | None = None) -> dict:
    return {
        "id": community.id,
        "name": community.name,
        "community_type": community.community_type,
        "description": community.description,
        "area": community.area,
        "country_code": community.country_code,
        "membership_role": membership.role if membership else None,
    }


def _is_member(db: Session, community_id: str, user_id: str) -> bool:
    return db.scalar(
        select(CommunityMembership.id).where(
            CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == user_id,
        )
    ) is not None


@router.get("/communities")
def list_communities(db: Db, page: int = 1, page_size: int = 20) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    query = select(Community).where(Community.is_active.is_(True)).order_by(Community.name)
    total = db.scalar(select(func.count()).select_from(Community).where(Community.is_active.is_(True))) or 0
    communities = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [_community_payload(community) for community in communities],
        meta={"pagination": {"page": page, "page_size": page_size, "total": total}},
    )


@router.post("/communities", status_code=status.HTTP_201_CREATED)
def create_community(payload: CommunityCreate, current_user: CurrentUserDependency, db: Db) -> dict:
    community = Community(
        name=payload.name,
        community_type=payload.community_type,
        description=payload.description,
        area=payload.area,
        country_code=payload.country_code,
        creator_id=current_user.user_id,
    )
    db.add(community)
    db.flush()
    membership = CommunityMembership(
        community_id=community.id,
        user_id=current_user.user_id,
        role="admin",
    )
    db.add(membership)
    record_audit(
        db,
        action="community.created",
        actor_id=current_user.user_id,
        entity_type="community",
        entity_id=community.id,
    )
    db.commit()
    return ok(_community_payload(community, membership))


@router.post("/communities/{community_id}/join", status_code=status.HTTP_201_CREATED)
def join_community(community_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    community = db.get(Community, community_id)
    if community is None or not community.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community not found.")
    if _is_member(db, community_id, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already a community member.")
    membership = CommunityMembership(community_id=community_id, user_id=current_user.user_id, role="member")
    db.add(membership)
    record_audit(
        db,
        action="community.member_joined",
        actor_id=current_user.user_id,
        entity_type="community_membership",
        entity_id=membership.id,
        details={"community_id": community_id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already a community member.") from exc
    return ok({"community_id": community_id, "role": membership.role})


@router.get("/communities/{community_id}/collection-points")
def list_collection_points(
    community_id: str,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    if not _is_member(db, community_id, current_user.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Community membership required.")
    points = db.scalars(
        select(CollectionPoint)
        .where(CollectionPoint.community_id == community_id, CollectionPoint.is_active.is_(True))
        .order_by(CollectionPoint.name)
    ).all()
    return ok(
        [
            {
                "id": point.id,
                "community_id": point.community_id,
                "name": point.name,
                "address_line": point.address_line,
                "operating_hours": point.operating_hours,
                "responsible_person": point.responsible_person,
                "latitude": point.latitude,
                "longitude": point.longitude,
            }
            for point in points
        ]
    )


@router.post("/communities/{community_id}/collection-points", status_code=status.HTTP_201_CREATED)
def create_collection_point(
    community_id: str,
    payload: CollectionPointCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    membership = db.scalar(
        select(CommunityMembership).where(
            CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == current_user.user_id,
        )
    )
    if membership is None or membership.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Community administrator access required.")
    point = CollectionPoint(community_id=community_id, **payload.model_dump())
    point.location = point_wkt(point.latitude, point.longitude)
    db.add(point)
    record_audit(
        db,
        action="collection_point.created",
        actor_id=current_user.user_id,
        entity_type="collection_point",
        entity_id=point.id,
        details={"community_id": community_id},
    )
    db.commit()
    return ok({"id": point.id, "community_id": community_id, "name": point.name})


@router.post("/addresses", status_code=status.HTTP_201_CREATED)
def create_address(payload: AddressCreate, current_user: CurrentUserDependency, db: Db) -> dict:
    address = Address(user_id=current_user.user_id, **payload.model_dump())
    address.location = point_wkt(address.latitude, address.longitude)
    db.add(address)
    record_audit(
        db,
        action="address.created",
        actor_id=current_user.user_id,
        entity_type="address",
        entity_id=address.id,
    )
    db.commit()
    return ok(_address_payload(address))


@router.get("/addresses")
def list_addresses(current_user: CurrentUserDependency, db: Db) -> dict:
    addresses = db.scalars(
        select(Address).where(Address.user_id == current_user.user_id).order_by(Address.created_at.desc())
    ).all()
    return ok([_address_payload(address) for address in addresses])


@router.patch("/addresses/{address_id}")
def update_address(
    address_id: str,
    payload: AddressUpdate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    address = db.get(Address, address_id)
    if address is None or address.user_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.")
    changes = payload.model_dump(exclude_unset=True)
    latitude = changes.get("latitude", address.latitude)
    longitude = changes.get("longitude", address.longitude)
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Latitude and longitude must be supplied together.")
    for field, value in changes.items():
        setattr(address, field, value)
    address.location = point_wkt(address.latitude, address.longitude)
    record_audit(
        db,
        action="address.updated",
        actor_id=current_user.user_id,
        entity_type="address",
        entity_id=address.id,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return ok(_address_payload(address))


@router.post("/agents/applications", status_code=status.HTTP_201_CREATED)
def apply_as_agent(current_user: CurrentUserDependency, db: Db) -> dict:
    application = db.scalar(select(CommunityAgent).where(CommunityAgent.user_id == current_user.user_id))
    if application is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An agent application already exists.")
    application = CommunityAgent(user_id=current_user.user_id, status="PENDING")
    db.add(application)
    record_audit(
        db,
        action="agent.application_submitted",
        actor_id=current_user.user_id,
        entity_type="community_agent",
        entity_id=application.id,
    )
    db.commit()
    return ok({"id": application.id, "status": application.status})


@router.post("/agents/{agent_id}/approve")
def approve_agent(
    agent_id: str,
    payload: AgentApprovalRequest,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    require_roles(current_user, Role.ADMIN, Role.STAFF)
    agent = db.get(CommunityAgent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent application not found.")
    if not payload.identity_verified:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Agent identity must be verified.")
    user = db.get(User, agent.user_id)
    if user is None or user.phone_verified_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent phone verification is required.")
    agent.status = "APPROVED"
    agent.identity_verified = True
    agent.reviewed_by = current_user.user_id
    agent.reviewed_at = datetime.now(timezone.utc)
    user.roles = list(set(user.roles or []).union({Role.COMMUNITY_AGENT.value}))
    record_audit(
        db,
        action="agent.approved",
        actor_id=current_user.user_id,
        entity_type="community_agent",
        entity_id=agent.id,
        details={"identity_verified": True},
    )
    db.commit()
    return ok({"id": agent.id, "status": agent.status})


@router.post("/agents/{agent_id}/suspend")
def suspend_agent(agent_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    require_roles(current_user, Role.ADMIN, Role.STAFF)
    agent = db.get(CommunityAgent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent application not found.")
    agent.status = "SUSPENDED"
    user = db.get(User, agent.user_id)
    if user is not None:
        user.roles = [role for role in user.roles or [] if role != Role.COMMUNITY_AGENT.value]
    record_audit(
        db,
        action="agent.suspended",
        actor_id=current_user.user_id,
        entity_type="community_agent",
        entity_id=agent.id,
    )
    db.commit()
    return ok({"id": agent.id, "status": agent.status})


@router.post("/communities/{community_id}/agents", status_code=status.HTTP_201_CREATED)
def assign_agent(
    community_id: str,
    payload: AgentAssignment,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    if not {Role.ADMIN.value, Role.STAFF.value}.intersection(current_user.roles):
        community_admin = db.scalar(
            select(CommunityMembership.id).where(
                CommunityMembership.community_id == community_id,
                CommunityMembership.user_id == current_user.user_id,
                CommunityMembership.role == "admin",
            )
        )
        if community_admin is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Community administrator access required.")
    community = db.get(Community, community_id)
    agent_user = db.get(User, payload.agent_id)
    agent = db.scalar(select(CommunityAgent).where(CommunityAgent.user_id == payload.agent_id))
    if community is None or agent is None or agent_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Community or agent not found.")
    if agent.status != "APPROVED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only approved agents can be assigned.")
    assignment = db.scalar(
        select(AgentCommunityAssignment).where(
            AgentCommunityAssignment.agent_id == payload.agent_id,
            AgentCommunityAssignment.community_id == community_id,
        )
    )
    if assignment is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is already assigned to this community.")
    assignment = AgentCommunityAssignment(
        agent_id=payload.agent_id,
        community_id=community_id,
        assigned_by=current_user.user_id,
    )
    db.add(assignment)
    record_audit(
        db,
        action="agent.assigned",
        actor_id=current_user.user_id,
        entity_type="agent_community_assignment",
        entity_id=assignment.id,
        details={"community_id": community_id, "agent_id": payload.agent_id},
    )
    db.commit()
    return ok({"id": assignment.id, "agent_id": payload.agent_id, "community_id": community_id})


@router.post("/members/{user_id}/agent-consents", status_code=status.HTTP_201_CREATED)
def create_agent_consent(
    user_id: str,
    payload: ConsentCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    if user_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the member can grant consent.")
    agent = db.scalar(select(CommunityAgent).where(CommunityAgent.user_id == payload.agent_id))
    if agent is None or agent.status != "APPROVED" or not agent.identity_verified:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approved agent not found.")
    shared_community = db.scalar(
        select(AgentCommunityAssignment.id)
        .join(
            CommunityMembership,
            CommunityMembership.community_id == AgentCommunityAssignment.community_id,
        )
        .where(
            AgentCommunityAssignment.agent_id == payload.agent_id,
            CommunityMembership.user_id == user_id,
        )
    )
    if shared_community is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent must be assigned to one of your communities.")
    consent = AgentConsent(
        member_id=user_id,
        agent_id=payload.agent_id,
        scopes=list(dict.fromkeys(payload.scopes)),
        expires_at=payload.expires_at,
    )
    db.add(consent)
    record_audit(
        db,
        action="agent_consent.granted",
        actor_id=user_id,
        entity_type="agent_consent",
        entity_id=consent.id,
        details={"agent_id": payload.agent_id, "scopes": consent.scopes, "expires_at": payload.expires_at.isoformat()},
    )
    db.commit()
    return ok(
        {
            "id": consent.id,
            "agent_id": consent.agent_id,
            "scopes": consent.scopes,
            "expires_at": consent.expires_at,
        }
    )


@router.delete("/members/{user_id}/agent-consents/{consent_id}")
def revoke_agent_consent(
    user_id: str,
    consent_id: str,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    if user_id != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the member can revoke consent.")
    consent = db.get(AgentConsent, consent_id)
    if consent is None or consent.member_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consent not found.")
    if consent.revoked_at is None:
        consent.revoked_at = datetime.now(timezone.utc)
        record_audit(
            db,
            action="agent_consent.revoked",
            actor_id=user_id,
            entity_type="agent_consent",
            entity_id=consent.id,
            details={"agent_id": consent.agent_id},
        )
        db.commit()
    return ok({"id": consent.id, "revoked": True})


@router.post("/farmers/role")
def enable_farmer_role(current_user: CurrentUserDependency, db: Db) -> dict:
    user = db.get(User, current_user.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active user not found.")
    if user.phone_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone verification is required before enabling farmer access.",
        )
    roles = list(user.roles or [])
    already_enabled = Role.FARMER.value in roles
    if not already_enabled:
        user.roles = list(dict.fromkeys([*roles, Role.FARMER.value]))
    user.permissions = list(
        dict.fromkeys(
            [
                *(user.permissions or []),
                Permission.READ_FARMERS.value,
                Permission.WRITE_FARMERS.value,
            ]
        )
    )
    record_audit(
        db,
        action="farmer.role_enabled",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"role": Role.FARMER.value, "already_enabled": already_enabled},
    )
    db.commit()
    return ok({"user_id": user.id, "role": Role.FARMER.value, "already_enabled": already_enabled})


@router.post("/members/{user_id}/farmer-role")
def enable_farmer_role_for_member(
    user_id: str,
    payload: FarmerRegistrationAssist,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    if Role.COMMUNITY_AGENT.value not in (current_user.roles or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an approved community agent may assist farmer registration.",
        )
    member = db.get(User, user_id)
    if member is None or not member.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active member not found.")
    if member.phone_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Member phone verification is required before farmer access can be enabled.",
        )
    consent = ensure_agent_consent(
        db,
        agent_id=current_user.user_id,
        member_id=member.id,
        scope="farmer:register",
        consent_id=payload.consent_id,
    )
    roles = list(member.roles or [])
    already_enabled = Role.FARMER.value in roles
    if not already_enabled:
        member.roles = list(dict.fromkeys([*roles, Role.FARMER.value]))
    member.permissions = list(
        dict.fromkeys(
            [
                *(member.permissions or []),
                Permission.READ_FARMERS.value,
                Permission.WRITE_FARMERS.value,
            ]
        )
    )
    record_audit(
        db,
        action="farmer.role_enabled_for_member",
        actor_id=current_user.user_id,
        entity_type="user",
        entity_id=member.id,
        details={
            "role": Role.FARMER.value,
            "consent_id": consent.id,
            "already_enabled": already_enabled,
        },
    )
    db.commit()
    return ok(
        {
            "user_id": member.id,
            "role": Role.FARMER.value,
            "already_enabled": already_enabled,
            "consent_id": consent.id,
        }
    )

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.deps.auth import CurrentUserDependency
from app.models.catalogue import Product, ProductGrade, Supplier, Unit
from app.models.identity import (
    AgentCommunityAssignment,
    AgentConsent,
    CollectionPoint,
    Community,
    CommunityAgent,
    CommunityMembership,
)
from app.models.outbox import OutboxEvent
from app.models.purchasing import (
    PurchaseGroup,
    PurchaseGroupMember,
    PurchaseGroupTarget,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseRequest,
    StandingBasket,
    StandingBasketCycle,
    StandingBasketParticipation,
    StandingBasketSubscription,
    StandingBasketTarget,
    SupplierQuotation,
    SupplierQuotationItem,
)
from app.models.user import User
from app.services.pricing import aware_datetime, create_baseline_snapshot
from app.shared.audit import record_audit
from app.shared.events import EventNames
from app.shared.responses import ok

router = APIRouter(prefix="/api/v1", tags=["purchasing"])
Db = Annotated[Session, Depends(get_db)]
DeliveryMethod = Literal["collection_point", "doorstep"]
Cadence = Literal["weekly", "monthly"]
Channel = Literal["app", "web", "ussd"]
AGENT_PLACE_SCOPE = "orders:place"
AGENT_AMEND_SCOPE = "orders:amend"


class GroupTargetInput(BaseModel):
    product_id: str
    grade_id: str
    unit_id: str
    minimum_quantity: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=6)


class PurchaseGroupCreate(BaseModel):
    community_id: str
    name: str = Field(min_length=2, max_length=160)
    area: str = Field(min_length=1, max_length=160)
    cutoff_at: datetime
    delivery_method: DeliveryMethod
    collection_point_id: str | None = None
    minimum_households: int | None = Field(default=None, gt=0)
    targets: list[GroupTargetInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def cutoff_is_aware_and_targets_are_unique(self) -> "PurchaseGroupCreate":
        if self.cutoff_at.tzinfo is None or self.cutoff_at.utcoffset() is None:
            raise ValueError("Cutoff must include a timezone.")
        keys = [(item.product_id, item.grade_id, item.unit_id) for item in self.targets]
        if len(set(keys)) != len(keys):
            raise ValueError("Purchase group targets must be unique.")
        if (self.delivery_method == "collection_point") != (self.collection_point_id is not None):
            raise ValueError("A collection point is required only for collection-point delivery.")
        return self


class PurchaseRequestCreate(BaseModel):
    target_id: str
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    member_id: str | None = None
    consent_id: str | None = None
    channel: Channel = "app"


class PurchaseRequestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    consent_id: str | None = None
    channel: Channel = "app"


class QuotationLineInput(BaseModel):
    target_id: str
    offered_quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_price_kobo: int = Field(ge=0)


class QuotationCreate(BaseModel):
    delivery_fee_kobo: int = Field(default=0, ge=0)
    handling_fee_kobo: int = Field(default=0, ge=0)
    other_fees_kobo: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    items: list[QuotationLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def item_targets_are_unique(self) -> "QuotationCreate":
        keys = [item.target_id for item in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("A quotation may contain each purchase target only once.")
        return self


class PurchaseGroupConfirm(BaseModel):
    quotation_id: str


class PurchaseOrderTransition(BaseModel):
    status: Literal["PROCESSING", "READY_FOR_PICKUP", "IN_TRANSIT", "DELIVERED", "DISPUTED"]


class BasketTargetInput(BaseModel):
    product_id: str
    grade_id: str
    unit_id: str
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)


class StandingBasketCreate(BaseModel):
    community_id: str
    name: str = Field(min_length=2, max_length=160)
    area: str = Field(min_length=1, max_length=160)
    cadence: Cadence
    cutoff_after_days: int = Field(ge=1)
    next_cycle_at: datetime
    delivery_method: DeliveryMethod
    collection_point_id: str | None = None
    targets: list[BasketTargetInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def schedule_and_targets_are_valid(self) -> "StandingBasketCreate":
        if self.next_cycle_at.tzinfo is None or self.next_cycle_at.utcoffset() is None:
            raise ValueError("The first cycle date must include a timezone.")
        keys = [(item.product_id, item.grade_id, item.unit_id) for item in self.targets]
        if len(set(keys)) != len(keys):
            raise ValueError("Standing-basket targets must be unique.")
        if (self.delivery_method == "collection_point") != (self.collection_point_id is not None):
            raise ValueError("A collection point is required only for collection-point delivery.")
        return self


def _is_staff(user: object) -> bool:
    return bool(set(getattr(user, "roles", []) or []).intersection({"admin", "staff"}))


def _is_community_manager(db: Session, community_id: str, user: object) -> bool:
    if _is_staff(user) or db.scalar(
        select(Community.id).where(
            Community.id == community_id,
            Community.creator_id == getattr(user, "user_id", None),
        )
    ):
        return True
    return db.scalar(
        select(CommunityMembership.id).where(
            CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == getattr(user, "user_id", None),
            CommunityMembership.role == "community_admin",
        )
    ) is not None


def _require_community_member(db: Session, community_id: str, user_id: str) -> None:
    membership = db.scalar(
        select(CommunityMembership.id).where(
            CommunityMembership.community_id == community_id,
            CommunityMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Active community membership is required.")


def _require_group_view(db: Session, group: PurchaseGroup, user: object) -> None:
    if _is_staff(user):
        return
    _require_community_member(db, group.community_id, getattr(user, "user_id", ""))


def _get_group(db: Session, group_id: str, *, lock: bool = False) -> PurchaseGroup:
    query = select(PurchaseGroup).where(PurchaseGroup.id == group_id)
    if lock:
        query = query.with_for_update()
    group = db.scalar(query)
    if group is None:
        raise HTTPException(status_code=404, detail="Purchase group not found.")
    return group


def _check_product_grade_unit(
    db: Session,
    product_id: str,
    grade_id: str,
    unit_id: str,
) -> tuple[Product, ProductGrade, Unit]:
    product = db.get(Product, product_id)
    grade = db.get(ProductGrade, grade_id)
    unit = db.get(Unit, unit_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found.")
    if grade is None or not grade.is_active or grade.product_id != product_id:
        raise HTTPException(status_code=422, detail="Grade does not belong to the selected product.")
    base_unit = db.get(Unit, product.base_unit_id)
    if unit is None or base_unit is None or unit.dimension != base_unit.dimension:
        raise HTTPException(status_code=422, detail="Unit is not compatible with this product.")
    return product, grade, unit


def _validate_collection_point(
    db: Session,
    community_id: str,
    delivery_method: str,
    collection_point_id: str | None,
) -> None:
    if delivery_method == "collection_point":
        point = db.get(CollectionPoint, collection_point_id) if collection_point_id else None
        if point is None or not point.is_active or point.community_id != community_id:
            raise HTTPException(status_code=422, detail="Active collection point in the selected community required.")


def _validate_targets(db: Session, targets: list[GroupTargetInput | BasketTargetInput]) -> None:
    for item in targets:
        _check_product_grade_unit(db, item.product_id, item.grade_id, item.unit_id)


def _group_target_payload(db: Session, target: PurchaseGroupTarget) -> dict:
    product = db.get(Product, target.product_id)
    grade = db.get(ProductGrade, target.grade_id)
    unit = db.get(Unit, target.unit_id)
    return {
        "id": target.id,
        "product_id": target.product_id,
        "product_name": product.name if product else None,
        "grade_id": target.grade_id,
        "grade_name": grade.name if grade else None,
        "unit_id": target.unit_id,
        "unit_code": unit.code if unit else None,
        "minimum_quantity": target.minimum_quantity,
    }


def _group_payload(db: Session, group: PurchaseGroup) -> dict:
    targets = db.scalars(
        select(PurchaseGroupTarget)
        .where(PurchaseGroupTarget.group_id == group.id)
        .order_by(PurchaseGroupTarget.id)
    ).all()
    return {
        "id": group.id,
        "community_id": group.community_id,
        "name": group.name,
        "area": group.area,
        "status": group.status,
        "cutoff_at": aware_datetime(group.cutoff_at),
        "delivery_method": group.delivery_method,
        "collection_point_id": group.collection_point_id,
        "minimum_households": group.minimum_households,
        "basket_id": group.basket_id,
        "targets": [_group_target_payload(db, target) for target in targets],
    }


def _group_is_open(group: PurchaseGroup) -> None:
    if group.status != "OPEN":
        raise HTTPException(status_code=409, detail="Purchase group is not open.")
    if aware_datetime(group.cutoff_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Purchase group cutoff has passed.")


def _active_consent(
    db: Session,
    *,
    member_id: str,
    agent_id: str,
    community_id: str,
    consent_id: str | None,
    scope: str,
) -> AgentConsent:
    agent = db.scalar(select(CommunityAgent).where(CommunityAgent.user_id == agent_id))
    assignment = db.scalar(
        select(AgentCommunityAssignment.id).where(
            AgentCommunityAssignment.agent_id == agent_id,
            AgentCommunityAssignment.community_id == community_id,
        )
    )
    membership = db.scalar(
        select(CommunityMembership.id).where(
            CommunityMembership.user_id == member_id,
            CommunityMembership.community_id == community_id,
        )
    )
    consent = db.get(AgentConsent, consent_id) if consent_id else None
    if agent is None or agent.status != "APPROVED" or not agent.identity_verified or assignment is None:
        raise HTTPException(status_code=403, detail="Approved agent assigned to the community is required.")
    if membership is None:
        raise HTTPException(status_code=403, detail="The member is not active in this community.")
    if (
        consent is None
        or consent.member_id != member_id
        or consent.agent_id != agent_id
        or consent.revoked_at is not None
        or aware_datetime(consent.expires_at) <= datetime.now(timezone.utc)
        or scope not in (consent.scopes or [])
    ):
        raise HTTPException(status_code=403, detail="Active consent for this action is required.")
    return consent


def _request_actor(
    db: Session,
    group: PurchaseGroup,
    payload: PurchaseRequestCreate | PurchaseRequestUpdate,
    current_user: object,
    *,
    scope: str,
    member_id: str | None = None,
) -> tuple[str, str | None, str | None, str]:
    roles = set(getattr(current_user, "roles", []) or [])
    user_id = getattr(current_user, "user_id", "")
    if "community_agent" not in roles:
        if member_id is not None and member_id != user_id:
            raise HTTPException(status_code=403, detail="Only an approved agent may submit for another member.")
        return user_id, None, None, payload.channel

    target_member_id = member_id if member_id is not None else getattr(payload, "member_id", None)
    if not target_member_id:
        raise HTTPException(status_code=422, detail="Agent requests must identify the member.")
    consent_id = payload.consent_id
    consent = _active_consent(
        db,
        member_id=target_member_id,
        agent_id=user_id,
        community_id=group.community_id,
        consent_id=consent_id,
        scope=scope,
    )
    return target_member_id, user_id, consent.id, "agent"


def _record_outbox(db: Session, event_name: str, payload: dict) -> None:
    db.add(OutboxEvent(event_name=event_name, payload=payload, status="PENDING"))


def _sum_group_demand(db: Session, group_id: str) -> tuple[list[dict], int]:
    requests = db.scalars(
        select(PurchaseRequest).where(
            PurchaseRequest.group_id == group_id,
            PurchaseRequest.status == "ACTIVE",
        )
    ).all()
    totals: dict[str, Decimal] = {}
    household_ids: set[str] = set()
    for request in requests:
        totals[request.target_id] = totals.get(request.target_id, Decimal("0")) + Decimal(request.quantity)
        household_ids.add(request.member_id)
    targets = {
        target.id: target
        for target in db.scalars(
            select(PurchaseGroupTarget).where(PurchaseGroupTarget.group_id == group_id)
        ).all()
    }
    aggregate: list[dict] = []
    for target_id, quantity in totals.items():
        target = targets[target_id]
        product = db.get(Product, target.product_id)
        grade = db.get(ProductGrade, target.grade_id)
        unit = db.get(Unit, target.unit_id)
        aggregate.append(
            {
                "target_id": target.id,
                "product_id": target.product_id,
                "product_name": product.name if product else None,
                "grade_id": target.grade_id,
                "grade_name": grade.name if grade else None,
                "unit_id": target.unit_id,
                "unit_code": unit.code if unit else None,
                "quantity": quantity,
            }
        )
    aggregate.sort(key=lambda line: (line["product_id"], line["grade_id"], line["unit_id"]))
    return aggregate, len(household_ids)


def _close_group(
    db: Session,
    group: PurchaseGroup,
    actor_id: str | None,
    *,
    now: datetime | None = None,
) -> None:
    if group.status != "OPEN":
        return
    current_time = aware_datetime(now or datetime.now(timezone.utc))
    if aware_datetime(group.cutoff_at) > current_time:
        raise HTTPException(status_code=409, detail="Purchase group cannot close before its cutoff.")
    aggregate, household_count = _sum_group_demand(db, group.id)
    group.status = "CLOSED"
    record_audit(
        db,
        action="purchase_group.closed",
        actor_id=actor_id,
        entity_type="purchase_group",
        entity_id=group.id,
        details={"household_count": household_count},
    )
    _record_outbox(db, EventNames.PURCHASE_GROUP_CLOSED, {"group_id": group.id})
    minimum = settings.demand_signal_min_households
    if minimum > 0 and household_count >= minimum and aggregate:
        _record_outbox(
            db,
            EventNames.PURCHASE_GROUP_DEMAND_PUBLISHED,
            {
                "area": group.area,
                "date_window": {
                    "start": aware_datetime(group.created_at).isoformat(),
                    "end": current_time.isoformat(),
                },
                "household_count": household_count,
                "items": [
                    {
                        "product_id": line["product_id"],
                        "grade_id": line["grade_id"],
                        "unit_id": line["unit_id"],
                        "quantity": str(line["quantity"]),
                    }
                    for line in aggregate
                ],
            },
        )
    else:
        _record_outbox(
            db,
            EventNames.PURCHASE_GROUP_DEMAND_WITHHELD,
            {
                "group_id": group.id,
                "reason": "THRESHOLD_NOT_CONFIGURED" if minimum == 0 else "BELOW_MINIMUM_HOUSEHOLDS",
            },
        )


def close_due_purchase_groups(db: Session, *, now: datetime | None = None) -> list[str]:
    current_time = aware_datetime(now or datetime.now(timezone.utc))
    groups = db.scalars(
        select(PurchaseGroup)
        .where(
            PurchaseGroup.status == "OPEN",
            PurchaseGroup.cutoff_at <= current_time,
        )
        .order_by(PurchaseGroup.cutoff_at, PurchaseGroup.id)
        .with_for_update()
    ).all()
    closed_ids: list[str] = []
    for group in groups:
        _close_group(db, group, None, now=current_time)
        closed_ids.append(group.id)
    if groups:
        db.commit()
    return closed_ids


@router.post("/purchase-groups", status_code=status.HTTP_201_CREATED)
def create_purchase_group(
    payload: PurchaseGroupCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    community = db.get(Community, payload.community_id)
    if community is None or not community.is_active:
        raise HTTPException(status_code=404, detail="Active community not found.")
    _require_community_member(db, community.id, current_user.user_id)
    if not _is_community_manager(db, community.id, current_user):
        raise HTTPException(status_code=403, detail="Community administrator access required.")
    if aware_datetime(payload.cutoff_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Purchase-group cutoff must be in the future.")
    _validate_collection_point(db, community.id, payload.delivery_method, payload.collection_point_id)
    _validate_targets(db, payload.targets)
    group = PurchaseGroup(
        community_id=community.id,
        created_by=current_user.user_id,
        name=payload.name.strip(),
        area=payload.area.strip(),
        cutoff_at=payload.cutoff_at,
        delivery_method=payload.delivery_method,
        collection_point_id=payload.collection_point_id,
        minimum_households=payload.minimum_households,
    )
    db.add(group)
    db.flush()
    for target in payload.targets:
        db.add(PurchaseGroupTarget(group_id=group.id, **target.model_dump()))
    record_audit(
        db,
        action="purchase_group.created",
        actor_id=current_user.user_id,
        entity_type="purchase_group",
        entity_id=group.id,
    )
    _record_outbox(db, EventNames.PURCHASE_GROUP_OPENED, {"group_id": group.id})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Purchase group conflicts with an existing record.") from exc
    db.refresh(group)
    return ok(_group_payload(db, group))


@router.get("/purchase-groups")
def list_purchase_groups(
    current_user: CurrentUserDependency,
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    query = (
        select(PurchaseGroup)
        .join(CommunityMembership, CommunityMembership.community_id == PurchaseGroup.community_id)
        .where(CommunityMembership.user_id == current_user.user_id)
        .order_by(PurchaseGroup.created_at.desc())
    )
    if _is_staff(current_user):
        query = select(PurchaseGroup).order_by(PurchaseGroup.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    groups = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [_group_payload(db, group) for group in groups],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/purchase-groups/{group_id}")
def get_purchase_group(group_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    group = _get_group(db, group_id)
    _require_group_view(db, group, current_user)
    return ok(_group_payload(db, group))


@router.post("/purchase-groups/{group_id}/join", status_code=status.HTTP_201_CREATED)
def join_purchase_group(group_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    group = _get_group(db, group_id, lock=True)
    _group_is_open(group)
    _require_community_member(db, group.community_id, current_user.user_id)
    membership = db.scalar(
        select(PurchaseGroupMember).where(
            PurchaseGroupMember.group_id == group.id,
            PurchaseGroupMember.user_id == current_user.user_id,
        )
    )
    if membership is None:
        membership = PurchaseGroupMember(group_id=group.id, user_id=current_user.user_id)
        db.add(membership)
        record_audit(
            db,
            action="purchase_group.member_joined",
            actor_id=current_user.user_id,
            entity_type="purchase_group",
            entity_id=group.id,
        )
        db.commit()
    return ok({"group_id": group.id, "joined": True})


@router.post("/purchase-groups/{group_id}/requests", status_code=status.HTTP_201_CREATED)
def create_purchase_request(
    group_id: str,
    payload: PurchaseRequestCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    group = _get_group(db, group_id, lock=True)
    _group_is_open(group)
    target = db.get(PurchaseGroupTarget, payload.target_id)
    if target is None or target.group_id != group.id:
        raise HTTPException(status_code=404, detail="Purchase-group target not found.")
    member_id, agent_id, consent_id, channel = _request_actor(
        db, group, payload, current_user, scope=AGENT_PLACE_SCOPE
    )
    member = db.get(User, member_id)
    if member is None or not member.is_active:
        raise HTTPException(status_code=404, detail="Active member not found.")
    group_member = db.scalar(
        select(PurchaseGroupMember).where(
            PurchaseGroupMember.group_id == group.id,
            PurchaseGroupMember.user_id == member_id,
        )
    )
    if group_member is None:
        raise HTTPException(status_code=403, detail="Member must join the purchase group first.")
    request = db.scalar(
        select(PurchaseRequest).where(
            PurchaseRequest.group_id == group.id,
            PurchaseRequest.target_id == target.id,
            PurchaseRequest.member_id == member_id,
        )
    )
    if request is None:
        request = PurchaseRequest(
            group_id=group.id,
            target_id=target.id,
            member_id=member_id,
            quantity=payload.quantity,
            placed_by_agent_id=agent_id,
            consent_id=consent_id,
            channel=channel,
        )
        db.add(request)
    elif request.status == "ACTIVE":
        raise HTTPException(status_code=409, detail="An active request already exists for this target.")
    else:
        request.quantity = payload.quantity
        request.status = "ACTIVE"
        request.placed_by_agent_id = agent_id
        request.consent_id = consent_id
        request.channel = channel
        request.withdrawn_at = None
    record_audit(
        db,
        action="purchase_request.submitted",
        actor_id=current_user.user_id,
        entity_type="purchase_request",
        entity_id=request.id,
        details={"member_id": member_id, "target_id": target.id, "placed_by_agent_id": agent_id},
    )
    db.flush()
    _record_outbox(
        db,
        EventNames.PURCHASE_REQUEST_SUBMITTED,
        {"request_id": request.id, "member_id": member_id, "group_id": group.id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A matching purchase request already exists.") from exc
    db.refresh(request)
    return ok(
        {
            "id": request.id,
            "group_id": request.group_id,
            "target_id": request.target_id,
            "member_id": request.member_id,
            "quantity": request.quantity,
            "status": request.status,
            "placed_by_agent_id": request.placed_by_agent_id,
            "consent_id": request.consent_id,
            "channel": request.channel,
            "created_at": aware_datetime(request.created_at),
        }
    )


def _get_request(db: Session, request_id: str, *, lock: bool = False) -> PurchaseRequest:
    query = select(PurchaseRequest).where(PurchaseRequest.id == request_id)
    if lock:
        query = query.with_for_update()
    request = db.scalar(query)
    if request is None:
        raise HTTPException(status_code=404, detail="Purchase request not found.")
    return request


def _authorize_request_change(
    db: Session,
    request: PurchaseRequest,
    current_user: object,
    consent_id: str | None,
) -> tuple[str | None, str | None]:
    user_id = getattr(current_user, "user_id", "")
    if request.member_id == user_id:
        return None, None
    if "community_agent" not in set(getattr(current_user, "roles", []) or []):
        raise HTTPException(status_code=403, detail="Only the member or an approved agent may change this request.")
    group = _get_group(db, request.group_id)
    consent = _active_consent(
        db,
        member_id=request.member_id,
        agent_id=user_id,
        community_id=group.community_id,
        consent_id=consent_id,
        scope=AGENT_AMEND_SCOPE,
    )
    return user_id, consent.id


def _assert_request_before_cutoff(group: PurchaseGroup) -> None:
    if group.status != "OPEN" or aware_datetime(group.cutoff_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Requests cannot be changed after the group cutoff.")


@router.patch("/purchase-requests/{request_id}")
def update_purchase_request(
    request_id: str,
    payload: PurchaseRequestUpdate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    request = _get_request(db, request_id, lock=True)
    group = _get_group(db, request.group_id, lock=True)
    _assert_request_before_cutoff(group)
    agent_id, consent_id = _authorize_request_change(db, request, current_user, payload.consent_id)
    if request.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Withdrawn request cannot be modified.")
    request.quantity = payload.quantity
    request.updated_at = datetime.now(timezone.utc)
    if agent_id is not None:
        request.placed_by_agent_id = agent_id
        request.consent_id = consent_id
        request.channel = "agent"
    record_audit(
        db,
        action="purchase_request.updated",
        actor_id=current_user.user_id,
        entity_type="purchase_request",
        entity_id=request.id,
        details={"quantity": str(payload.quantity), "placed_by_agent_id": agent_id},
    )
    db.commit()
    return ok({"id": request.id, "quantity": request.quantity, "status": request.status})


@router.delete("/purchase-requests/{request_id}")
def withdraw_purchase_request(
    request_id: str,
    current_user: CurrentUserDependency,
    db: Db,
    consent_id: str | None = None,
) -> dict:
    request = _get_request(db, request_id, lock=True)
    group = _get_group(db, request.group_id, lock=True)
    _assert_request_before_cutoff(group)
    agent_id, active_consent_id = _authorize_request_change(db, request, current_user, consent_id)
    if request.status != "WITHDRAWN":
        request.status = "WITHDRAWN"
        request.withdrawn_at = datetime.now(timezone.utc)
        record_audit(
            db,
            action="purchase_request.withdrawn",
            actor_id=current_user.user_id,
            entity_type="purchase_request",
            entity_id=request.id,
            details={"placed_by_agent_id": agent_id, "consent_id": active_consent_id},
        )
        db.commit()
    return ok({"id": request.id, "status": request.status})


@router.get("/purchase-groups/{group_id}/summary")
def get_purchase_group_summary(group_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    group = _get_group(db, group_id)
    _require_group_view(db, group, current_user)
    demand, household_count = _sum_group_demand(db, group.id)
    return ok(
        {
            "group_id": group.id,
            "household_count": household_count,
            "items": [
                {key: value for key, value in item.items() if key != "target_id"}
                for item in demand
            ],
        }
    )


@router.post("/purchase-groups/{group_id}/close")
def close_purchase_group(group_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    group = _get_group(db, group_id, lock=True)
    _require_group_view(db, group, current_user)
    if not _is_community_manager(db, group.community_id, current_user):
        raise HTTPException(status_code=403, detail="Community administrator access required.")
    if group.status == "OPEN":
        _close_group(db, group, current_user.user_id)
        db.commit()
    return ok({"group_id": group.id, "status": group.status})


@router.post("/purchase-groups/process-due")
def process_due_purchase_groups(current_user: CurrentUserDependency, db: Db) -> dict:
    if not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Staff access required.")
    closed_ids = close_due_purchase_groups(db)
    return ok({"closed_group_ids": closed_ids, "count": len(closed_ids)})


@router.post("/purchase-groups/{group_id}/cancel")
def cancel_purchase_group(group_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    group = _get_group(db, group_id, lock=True)
    if not _is_community_manager(db, group.community_id, current_user):
        raise HTTPException(status_code=403, detail="Community administrator access required.")
    if group.status == "CANCELLED":
        return ok({"group_id": group.id, "status": group.status})
    if group.status not in {"OPEN", "CLOSED", "QUOTING"}:
        raise HTTPException(status_code=409, detail="A confirmed purchase group cannot be cancelled here.")
    for request in db.scalars(
        select(PurchaseRequest).where(
            PurchaseRequest.group_id == group.id,
            PurchaseRequest.status == "ACTIVE",
        )
    ).all():
        request.status = "WITHDRAWN"
        request.withdrawn_at = datetime.now(timezone.utc)
    group.status = "CANCELLED"
    record_audit(
        db,
        action="purchase_group.cancelled",
        actor_id=current_user.user_id,
        entity_type="purchase_group",
        entity_id=group.id,
    )
    _record_outbox(db, EventNames.PURCHASE_GROUP_CANCELLED, {"group_id": group.id})
    db.commit()
    return ok({"group_id": group.id, "status": group.status})


def _quotation_total(
    db: Session,
    group: PurchaseGroup,
    payload: QuotationCreate,
) -> tuple[list[SupplierQuotationItem], int]:
    demand, _ = _sum_group_demand(db, group.id)
    demand_by_target = {item["target_id"]: item["quantity"] for item in demand}
    if not demand_by_target:
        raise HTTPException(status_code=409, detail="A group without active demand cannot receive quotations.")
    requests_by_target: dict[str, list[PurchaseRequest]] = {}
    for request in db.scalars(
        select(PurchaseRequest).where(
            PurchaseRequest.group_id == group.id,
            PurchaseRequest.status == "ACTIVE",
        )
    ).all():
        requests_by_target.setdefault(request.target_id, []).append(request)
    for target_id in demand_by_target:
        target = db.get(PurchaseGroupTarget, target_id)
        if target is None:
            raise HTTPException(status_code=409, detail="Purchase-group target is no longer available.")
        _check_product_grade_unit(db, target.product_id, target.grade_id, target.unit_id)
    items_by_target = {item.target_id: item for item in payload.items}
    if set(items_by_target) != set(demand_by_target):
        raise HTTPException(status_code=422, detail="Quotation must price every demanded target and no others.")
    quote_items: list[SupplierQuotationItem] = []
    subtotal = 0
    for target_id, quantity in demand_by_target.items():
        item = items_by_target[target_id]
        if item.offered_quantity < quantity:
            raise HTTPException(status_code=422, detail="Supplier offer does not cover the aggregated demand.")
        line_total = sum(
            int(
                (Decimal(request.quantity) * item.unit_price_kobo).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            for request in requests_by_target[target_id]
        )
        subtotal += line_total
        quote_items.append(
            SupplierQuotationItem(
                target_id=target_id,
                offered_quantity=item.offered_quantity,
                unit_price_kobo=item.unit_price_kobo,
                line_total_kobo=line_total,
            )
        )
    total = subtotal + payload.delivery_fee_kobo + payload.handling_fee_kobo + payload.other_fees_kobo
    return quote_items, total


@router.post("/purchase-groups/{group_id}/quotations", status_code=status.HTTP_201_CREATED)
def submit_supplier_quotation(
    group_id: str,
    payload: QuotationCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    group = _get_group(db, group_id, lock=True)
    if group.status not in {"CLOSED", "QUOTING"}:
        raise HTTPException(status_code=409, detail="Quotations are accepted only after group closure.")
    supplier = db.scalar(select(Supplier).where(Supplier.user_id == current_user.user_id))
    if supplier is None or supplier.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail="Verified supplier account required.")
    if db.scalar(
        select(SupplierQuotation.id).where(
            SupplierQuotation.group_id == group.id,
            SupplierQuotation.supplier_id == supplier.id,
        )
    ):
        raise HTTPException(status_code=409, detail="Supplier has already quoted for this group.")
    quote_items, total = _quotation_total(db, group, payload)
    quotation = SupplierQuotation(
        group_id=group.id,
        supplier_id=supplier.id,
        delivery_fee_kobo=payload.delivery_fee_kobo,
        handling_fee_kobo=payload.handling_fee_kobo,
        other_fees_kobo=payload.other_fees_kobo,
        total_delivered_kobo=total,
        notes=payload.notes,
    )
    db.add(quotation)
    db.flush()
    for item in quote_items:
        item.quotation_id = quotation.id
        db.add(item)
    group.status = "QUOTING"
    record_audit(
        db,
        action="supplier_quotation.submitted",
        actor_id=current_user.user_id,
        entity_type="supplier_quotation",
        entity_id=quotation.id,
        details={"group_id": group.id, "total_delivered_kobo": total},
    )
    _record_outbox(db, EventNames.QUOTATION_RECEIVED, {"quotation_id": quotation.id, "group_id": group.id})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supplier has already quoted for this group.") from exc
    db.refresh(quotation)
    return ok(_quotation_payload(db, quotation))


def _quotation_payload(db: Session, quotation: SupplierQuotation) -> dict:
    supplier = db.get(Supplier, quotation.supplier_id)
    items = db.scalars(
        select(SupplierQuotationItem)
        .where(SupplierQuotationItem.quotation_id == quotation.id)
        .order_by(SupplierQuotationItem.target_id)
    ).all()
    return {
        "id": quotation.id,
        "supplier_id": quotation.supplier_id,
        "supplier_name": supplier.business_name if supplier else None,
        "total_delivered_kobo": quotation.total_delivered_kobo,
        "delivery_fee_kobo": quotation.delivery_fee_kobo,
        "handling_fee_kobo": quotation.handling_fee_kobo,
        "other_fees_kobo": quotation.other_fees_kobo,
        "currency": quotation.currency,
        "notes": quotation.notes,
        "submitted_at": aware_datetime(quotation.submitted_at),
        "items": [
            {
                "target": _group_target_payload(
                    db,
                    db.get(PurchaseGroupTarget, item.target_id),
                ),
                "offered_quantity": item.offered_quantity,
                "unit_price_kobo": item.unit_price_kobo,
                "line_total_kobo": item.line_total_kobo,
            }
            for item in items
        ],
    }


@router.get("/purchase-groups/{group_id}/quotations")
def list_supplier_quotations(
    group_id: str,
    current_user: CurrentUserDependency,
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    group = _get_group(db, group_id)
    _require_group_view(db, group, current_user)
    query = select(SupplierQuotation).where(SupplierQuotation.group_id == group.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    quotations = db.scalars(
        query.order_by(SupplierQuotation.total_delivered_kobo, SupplierQuotation.submitted_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ok(
        [_quotation_payload(db, quote) for quote in quotations],
        meta={"page": page, "page_size": page_size, "total": total},
    )


def _allocate_fee(total_fee: int, weights: dict[str, int]) -> dict[str, int]:
    if not weights:
        return {}
    total_weight = sum(weights.values())
    effective_weights = weights if total_weight else {key: 1 for key in weights}
    total_weight = sum(effective_weights.values())
    allocations = {key: total_fee * weight // total_weight for key, weight in effective_weights.items()}
    remainder = total_fee - sum(allocations.values())
    priority = sorted(
        effective_weights,
        key=lambda key: (-(total_fee * effective_weights[key] % total_weight), key),
    )
    for key in priority[:remainder]:
        allocations[key] += 1
    return allocations


def _order_payload(db: Session, order: PurchaseOrder) -> dict:
    items = db.scalars(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order.id)
    ).all()
    return {
        "id": order.id,
        "group_id": order.group_id,
        "status": order.status,
        "delivery_method": order.delivery_method,
        "subtotal_kobo": order.subtotal_kobo,
        "delivery_fee_kobo": order.delivery_fee_kobo,
        "handling_fee_kobo": order.handling_fee_kobo,
        "other_fees_kobo": order.other_fees_kobo,
        "total_amount_kobo": order.total_amount_kobo,
        "currency": "NGN",
        "quotation_id": order.quotation_id,
        "items": [
            {
                "id": item.id,
                "target_id": item.target_id,
                "quantity": item.quantity,
                "unit_price_kobo": item.unit_price_kobo,
                "line_total_kobo": item.line_total_kobo,
                "baseline_snapshot_id": item.baseline_snapshot_id,
            }
            for item in items
        ],
        "created_at": aware_datetime(order.created_at),
    }


@router.post("/purchase-groups/{group_id}/confirm")
def confirm_purchase_group(
    group_id: str,
    payload: PurchaseGroupConfirm,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    group = _get_group(db, group_id, lock=True)
    if not _is_community_manager(db, group.community_id, current_user):
        raise HTTPException(status_code=403, detail="Community administrator access required.")
    if group.status == "CONFIRMED":
        if group.selected_quotation_id != payload.quotation_id:
            raise HTTPException(status_code=409, detail="A different quotation has already been confirmed.")
        orders = db.scalars(
            select(PurchaseOrder).where(PurchaseOrder.group_id == group.id).order_by(PurchaseOrder.member_id)
        ).all()
        return ok(
            {
                "group_id": group.id,
                "status": group.status,
                "quotation_id": payload.quotation_id,
                "order_count": len(orders),
                "orders": [_order_payload(db, order) for order in orders],
            }
        )
    if group.status != "QUOTING":
        raise HTTPException(status_code=409, detail="Group must be in quotation state before confirmation.")
    quotation = db.get(SupplierQuotation, payload.quotation_id)
    if quotation is None or quotation.group_id != group.id:
        raise HTTPException(status_code=404, detail="Quotation not found for this group.")
    supplier = db.get(Supplier, quotation.supplier_id)
    if supplier is None or supplier.verification_status != "VERIFIED":
        raise HTTPException(status_code=409, detail="Selected supplier is no longer verified.")
    demand, household_count = _sum_group_demand(db, group.id)
    if not demand:
        raise HTTPException(status_code=409, detail="A group without active demand cannot be confirmed.")
    if group.minimum_households is not None and household_count < group.minimum_households:
        raise HTTPException(status_code=409, detail="Group has not reached its configured household minimum.")
    for line in demand:
        target = db.get(PurchaseGroupTarget, line["target_id"])
        if target.minimum_quantity is not None and line["quantity"] < target.minimum_quantity:
            raise HTTPException(status_code=409, detail="Group has not reached a configured target quantity.")

    request_rows = db.scalars(
        select(PurchaseRequest)
        .where(PurchaseRequest.group_id == group.id, PurchaseRequest.status == "ACTIVE")
        .order_by(PurchaseRequest.member_id, PurchaseRequest.target_id)
    ).all()
    quote_items = {
        item.target_id: item
        for item in db.scalars(
            select(SupplierQuotationItem).where(SupplierQuotationItem.quotation_id == quotation.id)
        ).all()
    }
    demand_by_target = {line["target_id"]: line["quantity"] for line in demand}
    if set(quote_items) != set(demand_by_target):
        raise HTTPException(status_code=409, detail="Selected quotation no longer matches the group's demand.")
    if any(quote_items[target].offered_quantity < quantity for target, quantity in demand_by_target.items()):
        raise HTTPException(status_code=409, detail="Selected quotation no longer covers the group's demand.")

    member_requests: dict[str, list[PurchaseRequest]] = {}
    member_subtotals: dict[str, int] = {}
    for request in request_rows:
        member_requests.setdefault(request.member_id, []).append(request)
        quote_item = quote_items[request.target_id]
        amount = int(
            (Decimal(request.quantity) * quote_item.unit_price_kobo).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        member_subtotals[request.member_id] = member_subtotals.get(request.member_id, 0) + amount
    delivery_allocations = _allocate_fee(quotation.delivery_fee_kobo, member_subtotals)
    handling_allocations = _allocate_fee(quotation.handling_fee_kobo, member_subtotals)
    other_allocations = _allocate_fee(quotation.other_fees_kobo, member_subtotals)
    group_targets = {
        target.id: target
        for target in db.scalars(
            select(PurchaseGroupTarget).where(PurchaseGroupTarget.group_id == group.id)
        ).all()
    }
    created_orders: list[PurchaseOrder] = []
    for member_id in sorted(member_requests):
        subtotal = member_subtotals[member_id]
        delivery = delivery_allocations[member_id]
        handling = handling_allocations[member_id]
        other = other_allocations[member_id]
        order = PurchaseOrder(
            group_id=group.id,
            member_id=member_id,
            quotation_id=quotation.id,
            supplier_id=quotation.supplier_id,
            status="PENDING_PAYMENT",
            delivery_method=group.delivery_method,
            subtotal_kobo=subtotal,
            delivery_fee_kobo=delivery,
            handling_fee_kobo=handling,
            other_fees_kobo=other,
            total_amount_kobo=subtotal + delivery + handling + other,
        )
        db.add(order)
        db.flush()
        for request in member_requests[member_id]:
            target = group_targets[request.target_id]
            product, grade, unit = _check_product_grade_unit(
                db,
                target.product_id,
                target.grade_id,
                target.unit_id,
            )
            baseline = create_baseline_snapshot(
                db,
                product=product,
                grade=grade,
                requested_unit=unit,
                area=group.area,
                quantity=Decimal(request.quantity),
                created_by=current_user.user_id,
            )
            db.add(baseline)
            db.flush()
            quote_item = quote_items[request.target_id]
            line_total = int(
                (Decimal(request.quantity) * quote_item.unit_price_kobo).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            db.add(
                PurchaseOrderItem(
                    order_id=order.id,
                    request_id=request.id,
                    target_id=target.id,
                    quantity=request.quantity,
                    unit_price_kobo=quote_item.unit_price_kobo,
                    line_total_kobo=line_total,
                    baseline_snapshot_id=baseline.id,
                )
            )
        record_audit(
            db,
            action="purchase_order.created",
            actor_id=current_user.user_id,
            entity_type="purchase_order",
            entity_id=order.id,
            details={"group_id": group.id, "member_id": member_id, "total_amount_kobo": order.total_amount_kobo},
        )
        _record_outbox(db, EventNames.ORDER_CREATED, {"order_id": order.id, "member_id": member_id})
        created_orders.append(order)

    group.status = "CONFIRMED"
    group.selected_quotation_id = quotation.id
    group.confirmed_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="supplier_quotation.approved",
        actor_id=current_user.user_id,
        entity_type="supplier_quotation",
        entity_id=quotation.id,
        details={"group_id": group.id},
    )
    _record_outbox(db, EventNames.QUOTATION_APPROVED, {"quotation_id": quotation.id, "group_id": group.id})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Purchase orders were already created for this group.") from exc
    for order in created_orders:
        db.refresh(order)
    return ok(
        {
            "group_id": group.id,
            "status": group.status,
            "quotation_id": quotation.id,
            "order_count": len(created_orders),
            "orders": [_order_payload(db, order) for order in created_orders],
        }
    )


def _next_cycle(start: datetime, cadence: str, anchor_day: int) -> datetime:
    if cadence == "weekly":
        return start + timedelta(days=7)
    next_month = start.month % 12 + 1
    year = start.year + (1 if start.month == 12 else 0)
    return start.replace(
        year=year,
        month=next_month,
        day=min(anchor_day, calendar.monthrange(year, next_month)[1]),
    )


def open_due_basket_cycles(db: Session, *, now: datetime | None = None) -> list[dict]:
    current_time = aware_datetime(now or datetime.now(timezone.utc))
    baskets = db.scalars(
        select(StandingBasket)
        .where(StandingBasket.is_active.is_(True), StandingBasket.next_cycle_at <= current_time)
        .order_by(StandingBasket.next_cycle_at, StandingBasket.id)
        .with_for_update()
    ).all()
    opened: list[dict] = []
    for basket in baskets:
        cycle_start = aware_datetime(basket.next_cycle_at)
        existing = db.scalar(
            select(StandingBasketCycle).where(
                StandingBasketCycle.basket_id == basket.id,
                StandingBasketCycle.cycle_start == basket.next_cycle_at,
            )
        )
        cycle_end = _next_cycle(cycle_start, basket.cadence, basket.cycle_anchor_day)
        if existing is None:
            cutoff_at = min(cycle_start + timedelta(days=basket.cutoff_after_days), cycle_end)
            community = db.get(Community, basket.community_id)
            if community is None or not community.is_active:
                basket.is_active = False
                continue
            group = PurchaseGroup(
                community_id=basket.community_id,
                created_by=basket.created_by,
                basket_id=basket.id,
                name=basket.name,
                area=basket.area,
                status="OPEN" if current_time < cutoff_at else "CLOSED",
                cutoff_at=cutoff_at,
                delivery_method=basket.delivery_method,
                collection_point_id=basket.collection_point_id,
            )
            db.add(group)
            db.flush()
            basket_targets = db.scalars(
                select(StandingBasketTarget)
                .where(StandingBasketTarget.basket_id == basket.id)
                .order_by(StandingBasketTarget.id)
            ).all()
            for item in basket_targets:
                db.add(
                    PurchaseGroupTarget(
                        group_id=group.id,
                        product_id=item.product_id,
                        grade_id=item.grade_id,
                        unit_id=item.unit_id,
                    )
                )
            cycle = StandingBasketCycle(
                basket_id=basket.id,
                purchase_group_id=group.id,
                cycle_start=cycle_start,
                cycle_end=cycle_end,
                cutoff_at=cutoff_at,
            )
            db.add(cycle)
            db.flush()
            _record_outbox(db, EventNames.BASKET_CYCLE_OPENED, {"basket_id": basket.id, "group_id": group.id})
            record_audit(
                db,
                action="standing_basket.cycle_opened",
                actor_id=basket.created_by,
                entity_type="standing_basket_cycle",
                entity_id=cycle.id,
                details={"group_id": group.id, "status": group.status},
            )
            opened.append(
                {
                    "basket_id": basket.id,
                    "cycle_id": cycle.id,
                    "cycle_start": cycle_start,
                    "group_id": group.id,
                    "cutoff_at": cutoff_at,
                    "status": group.status,
                }
            )
        basket.next_cycle_at = cycle_end
    if baskets:
        db.commit()
    return opened


@router.post("/baskets", status_code=status.HTTP_201_CREATED)
def create_standing_basket(
    payload: StandingBasketCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    community = db.get(Community, payload.community_id)
    if community is None or not community.is_active:
        raise HTTPException(status_code=404, detail="Active community not found.")
    _require_community_member(db, community.id, current_user.user_id)
    if not _is_community_manager(db, community.id, current_user):
        raise HTTPException(status_code=403, detail="Community administrator access required.")
    _validate_collection_point(db, community.id, payload.delivery_method, payload.collection_point_id)
    _validate_targets(db, payload.targets)
    basket = StandingBasket(
        community_id=community.id,
        created_by=current_user.user_id,
        name=payload.name.strip(),
        area=payload.area.strip(),
        cadence=payload.cadence,
        cutoff_after_days=payload.cutoff_after_days,
        cycle_anchor_day=payload.next_cycle_at.day,
        next_cycle_at=payload.next_cycle_at,
        delivery_method=payload.delivery_method,
        collection_point_id=payload.collection_point_id,
    )
    db.add(basket)
    db.flush()
    for target in payload.targets:
        db.add(StandingBasketTarget(basket_id=basket.id, **target.model_dump()))
    record_audit(
        db,
        action="standing_basket.created",
        actor_id=current_user.user_id,
        entity_type="standing_basket",
        entity_id=basket.id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Standing basket conflicts with an existing record.") from exc
    db.refresh(basket)
    return ok(_basket_payload(db, basket, current_user.user_id))


def _basket_payload(db: Session, basket: StandingBasket, user_id: str) -> dict:
    targets = db.scalars(
        select(StandingBasketTarget)
        .where(StandingBasketTarget.basket_id == basket.id)
        .order_by(StandingBasketTarget.id)
    ).all()
    subscription = db.scalar(
        select(StandingBasketSubscription).where(
            StandingBasketSubscription.basket_id == basket.id,
            StandingBasketSubscription.user_id == user_id,
        )
    )
    return {
        "id": basket.id,
        "community_id": basket.community_id,
        "name": basket.name,
        "area": basket.area,
        "cadence": basket.cadence,
        "cutoff_after_days": basket.cutoff_after_days,
        "next_cycle_at": aware_datetime(basket.next_cycle_at),
        "delivery_method": basket.delivery_method,
        "collection_point_id": basket.collection_point_id,
        "is_active": basket.is_active,
        "is_subscribed": bool(subscription and subscription.is_active),
        "targets": [
            {
                "product_id": item.product_id,
                "grade_id": item.grade_id,
                "unit_id": item.unit_id,
                "quantity": item.quantity,
            }
            for item in targets
        ],
    }


def _get_basket(db: Session, basket_id: str) -> StandingBasket:
    basket = db.get(StandingBasket, basket_id)
    if basket is None:
        raise HTTPException(status_code=404, detail="Standing basket not found.")
    return basket


@router.get("/baskets")
def list_standing_baskets(
    current_user: CurrentUserDependency,
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    query = (
        select(StandingBasket)
        .join(CommunityMembership, CommunityMembership.community_id == StandingBasket.community_id)
        .where(CommunityMembership.user_id == current_user.user_id, StandingBasket.is_active.is_(True))
        .order_by(StandingBasket.created_at.desc())
    )
    if _is_staff(current_user):
        query = select(StandingBasket).where(StandingBasket.is_active.is_(True)).order_by(StandingBasket.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    baskets = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [_basket_payload(db, basket, current_user.user_id) for basket in baskets],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/baskets/{basket_id}")
def get_standing_basket(basket_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    basket = _get_basket(db, basket_id)
    if not _is_staff(current_user):
        _require_community_member(db, basket.community_id, current_user.user_id)
    return ok(_basket_payload(db, basket, current_user.user_id))


@router.get("/baskets/{basket_id}/cycles")
def list_basket_cycles(
    basket_id: str,
    current_user: CurrentUserDependency,
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    basket = _get_basket(db, basket_id)
    if not _is_staff(current_user):
        _require_community_member(db, basket.community_id, current_user.user_id)
    query = select(StandingBasketCycle).where(StandingBasketCycle.basket_id == basket.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    cycles = db.scalars(
        query.order_by(StandingBasketCycle.cycle_start.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    participations = {
        participation.cycle_id: participation.status
        for participation in db.scalars(
            select(StandingBasketParticipation).where(
                StandingBasketParticipation.user_id == current_user.user_id,
                StandingBasketParticipation.cycle_id.in_([cycle.id for cycle in cycles] or [""]),
            )
        ).all()
    }
    return ok(
        [
            {
                "id": cycle.id,
                "group_id": cycle.purchase_group_id,
                "cycle_start": aware_datetime(cycle.cycle_start),
                "cycle_end": aware_datetime(cycle.cycle_end),
                "cutoff_at": aware_datetime(cycle.cutoff_at),
                "participation_status": participations.get(cycle.id),
            }
            for cycle in cycles
        ],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/baskets/{basket_id}/subscribe")
def subscribe_to_basket(basket_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    basket = _get_basket(db, basket_id)
    if not basket.is_active:
        raise HTTPException(status_code=409, detail="Standing basket is not active.")
    _require_community_member(db, basket.community_id, current_user.user_id)
    subscription = db.scalar(
        select(StandingBasketSubscription).where(
            StandingBasketSubscription.basket_id == basket.id,
            StandingBasketSubscription.user_id == current_user.user_id,
        )
    )
    if subscription is None:
        subscription = StandingBasketSubscription(basket_id=basket.id, user_id=current_user.user_id)
        db.add(subscription)
    else:
        subscription.is_active = True
        subscription.cancelled_at = None
    record_audit(
        db,
        action="standing_basket.subscribed",
        actor_id=current_user.user_id,
        entity_type="standing_basket",
        entity_id=basket.id,
    )
    db.commit()
    return ok({"basket_id": basket.id, "subscribed": True})


@router.delete("/baskets/{basket_id}/subscribe")
def unsubscribe_from_basket(basket_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    basket = _get_basket(db, basket_id)
    _require_community_member(db, basket.community_id, current_user.user_id)
    subscription = db.scalar(
        select(StandingBasketSubscription).where(
            StandingBasketSubscription.basket_id == basket.id,
            StandingBasketSubscription.user_id == current_user.user_id,
        )
    )
    if subscription is not None and subscription.is_active:
        subscription.is_active = False
        subscription.cancelled_at = datetime.now(timezone.utc)
        record_audit(
            db,
            action="standing_basket.unsubscribed",
            actor_id=current_user.user_id,
            entity_type="standing_basket",
            entity_id=basket.id,
        )
        db.commit()
    return ok({"basket_id": basket.id, "subscribed": False})


def _get_cycle(db: Session, cycle_id: str) -> tuple[StandingBasketCycle, StandingBasket, PurchaseGroup]:
    cycle = db.get(StandingBasketCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Standing-basket cycle not found.")
    basket = _get_basket(db, cycle.basket_id)
    group = _get_group(db, cycle.purchase_group_id)
    return cycle, basket, group


@router.post("/baskets/{basket_id}/cycles/{cycle_id}/join")
def join_basket_cycle(
    basket_id: str,
    cycle_id: str,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    cycle, basket, group = _get_cycle(db, cycle_id)
    if cycle.basket_id != basket_id:
        raise HTTPException(status_code=404, detail="Cycle does not belong to this basket.")
    _group_is_open(group)
    subscription = db.scalar(
        select(StandingBasketSubscription).where(
            StandingBasketSubscription.basket_id == basket.id,
            StandingBasketSubscription.user_id == current_user.user_id,
            StandingBasketSubscription.is_active.is_(True),
        )
    )
    if subscription is None:
        raise HTTPException(status_code=403, detail="Subscribe to the standing basket before joining a cycle.")
    _require_community_member(db, basket.community_id, current_user.user_id)
    participation = db.scalar(
        select(StandingBasketParticipation).where(
            StandingBasketParticipation.cycle_id == cycle.id,
            StandingBasketParticipation.user_id == current_user.user_id,
        )
    )
    if participation is None:
        participation = StandingBasketParticipation(cycle_id=cycle.id, user_id=current_user.user_id)
        db.add(participation)
    else:
        participation.status = "OPTED_IN"
        participation.left_at = None
    group_member = db.scalar(
        select(PurchaseGroupMember).where(
            PurchaseGroupMember.group_id == group.id,
            PurchaseGroupMember.user_id == current_user.user_id,
        )
    )
    if group_member is None:
        db.add(PurchaseGroupMember(group_id=group.id, user_id=current_user.user_id))
    target_map = {
        (item.product_id, item.grade_id, item.unit_id): item
        for item in db.scalars(
            select(PurchaseGroupTarget).where(PurchaseGroupTarget.group_id == group.id)
        ).all()
    }
    for item in db.scalars(
        select(StandingBasketTarget).where(StandingBasketTarget.basket_id == basket.id)
    ).all():
        target = target_map[(item.product_id, item.grade_id, item.unit_id)]
        request = db.scalar(
            select(PurchaseRequest).where(
                PurchaseRequest.group_id == group.id,
                PurchaseRequest.target_id == target.id,
                PurchaseRequest.member_id == current_user.user_id,
            )
        )
        if request is None:
            db.add(
                PurchaseRequest(
                    group_id=group.id,
                    target_id=target.id,
                    member_id=current_user.user_id,
                    quantity=item.quantity,
                    channel="app",
                )
            )
        else:
            request.quantity = item.quantity
            request.status = "ACTIVE"
            request.withdrawn_at = None
    record_audit(
        db,
        action="standing_basket.cycle_joined",
        actor_id=current_user.user_id,
        entity_type="standing_basket_cycle",
        entity_id=cycle.id,
    )
    db.commit()
    return ok({"basket_id": basket.id, "cycle_id": cycle.id, "status": "OPTED_IN"})


def _leave_cycle(
    db: Session,
    cycle: StandingBasketCycle,
    group: PurchaseGroup,
    user_id: str,
    state: Literal["SKIPPED", "LEFT"],
) -> None:
    if group.status != "OPEN" or aware_datetime(cycle.cutoff_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Cycle can no longer be changed after its cutoff.")
    participation = db.scalar(
        select(StandingBasketParticipation).where(
            StandingBasketParticipation.cycle_id == cycle.id,
            StandingBasketParticipation.user_id == user_id,
        )
    )
    if participation is None and state == "SKIPPED":
        participation = StandingBasketParticipation(
            cycle_id=cycle.id,
            user_id=user_id,
            status="SKIPPED",
            left_at=datetime.now(timezone.utc),
        )
        db.add(participation)
    elif participation is not None:
        participation.status = state
        participation.left_at = datetime.now(timezone.utc)
    for request in db.scalars(
        select(PurchaseRequest).where(
            PurchaseRequest.group_id == group.id,
            PurchaseRequest.member_id == user_id,
            PurchaseRequest.status == "ACTIVE",
        )
    ).all():
        request.status = "WITHDRAWN"
        request.withdrawn_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action=f"standing_basket.cycle_{state.lower()}",
        actor_id=user_id,
        entity_type="standing_basket_cycle",
        entity_id=cycle.id,
    )
    if state == "SKIPPED":
        _record_outbox(db, EventNames.BASKET_CYCLE_SKIPPED, {"basket_id": cycle.basket_id, "cycle_id": cycle.id})
    db.commit()


@router.post("/baskets/{basket_id}/cycles/{cycle_id}/skip")
def skip_basket_cycle(
    basket_id: str,
    cycle_id: str,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    cycle, basket, group = _get_cycle(db, cycle_id)
    if cycle.basket_id != basket_id:
        raise HTTPException(status_code=404, detail="Cycle does not belong to this basket.")
    _require_community_member(db, basket.community_id, current_user.user_id)
    _leave_cycle(db, cycle, group, current_user.user_id, "SKIPPED")
    return ok({"basket_id": basket.id, "cycle_id": cycle.id, "status": "SKIPPED"})


@router.delete("/baskets/{basket_id}/cycles/{cycle_id}/participation")
def leave_basket_cycle(
    basket_id: str,
    cycle_id: str,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    cycle, basket, group = _get_cycle(db, cycle_id)
    if cycle.basket_id != basket_id:
        raise HTTPException(status_code=404, detail="Cycle does not belong to this basket.")
    _require_community_member(db, basket.community_id, current_user.user_id)
    _leave_cycle(db, cycle, group, current_user.user_id, "LEFT")
    return ok({"basket_id": basket.id, "cycle_id": cycle.id, "status": "LEFT"})


@router.post("/baskets/process-due-cycles")
def process_due_basket_cycles(current_user: CurrentUserDependency, db: Db) -> dict:
    if not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Staff access required.")
    opened = open_due_basket_cycles(db)
    return ok({"opened_cycles": opened, "count": len(opened)})


def _order_visible_to_user(order: PurchaseOrder, user: object) -> bool:
    return _is_staff(user) or order.member_id == getattr(user, "user_id", None)


@router.get("/orders")
def list_orders(
    current_user: CurrentUserDependency,
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    query = select(PurchaseOrder)
    if not _is_staff(current_user):
        query = query.where(PurchaseOrder.member_id == current_user.user_id)
    query = query.order_by(PurchaseOrder.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    orders = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [_order_payload(db, order) for order in orders],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/orders/{order_id}")
def get_order(order_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    order = db.get(PurchaseOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    if not _order_visible_to_user(order, current_user):
        raise HTTPException(status_code=404, detail="Order not found.")
    return ok(_order_payload(db, order))


@router.post("/orders/{order_id}/status")
def transition_order_status(
    order_id: str,
    payload: PurchaseOrderTransition,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    order = db.scalar(
        select(PurchaseOrder).where(PurchaseOrder.id == order_id).with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    group = _get_group(db, order.group_id, lock=True)
    target_status = payload.status
    roles = set(getattr(current_user, "roles", []) or [])
    is_staff = bool(roles.intersection({"admin", "staff"}))
    if target_status == "PROCESSING":
        supplier = db.get(Supplier, order.supplier_id)
        if order.status != "PAID":
            raise HTTPException(status_code=409, detail="Order must have verified payment before processing.")
        if not is_staff and (supplier is None or supplier.user_id != current_user.user_id):
            raise HTTPException(status_code=403, detail="Supplier owner access required.")
        event_name = EventNames.ORDER_PROCESSING
    elif target_status in {"READY_FOR_PICKUP", "IN_TRANSIT"}:
        if order.status != "PROCESSING" or not is_staff:
            raise HTTPException(status_code=403, detail="Staff may move a processing order to delivery.")
        expected = "READY_FOR_PICKUP" if group.delivery_method == "collection_point" else "IN_TRANSIT"
        if target_status != expected:
            raise HTTPException(status_code=422, detail="Order status does not match its delivery method.")
        event_name = EventNames.ORDER_READY if target_status == "READY_FOR_PICKUP" else EventNames.ORDER_IN_TRANSIT
    elif target_status == "DELIVERED":
        allowed_previous = {"READY_FOR_PICKUP", "IN_TRANSIT"}
        if order.status not in allowed_previous or not is_staff:
            raise HTTPException(status_code=403, detail="Staff may complete an order in delivery.")
        expected_previous = "READY_FOR_PICKUP" if group.delivery_method == "collection_point" else "IN_TRANSIT"
        if order.status != expected_previous:
            raise HTTPException(status_code=409, detail="Order has not reached its required delivery state.")
        event_name = EventNames.DELIVERY_DELIVERED
    else:
        if order.status != "DELIVERED":
            raise HTTPException(status_code=409, detail="Only a delivered order may be disputed.")
        if not is_staff and order.member_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="Only the customer or staff may dispute the order.")
        event_name = EventNames.ORDER_DISPUTED

    previous_status = order.status
    order.status = target_status
    order.updated_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="purchase_order.status_changed",
        actor_id=current_user.user_id,
        entity_type="purchase_order",
        entity_id=order.id,
        details={"from": previous_status, "to": target_status},
    )
    if target_status in {"PROCESSING", "READY_FOR_PICKUP", "IN_TRANSIT"}:
        group.status = "FULFILLING"
    elif target_status == "DELIVERED":
        other_orders = db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.group_id == group.id,
                PurchaseOrder.id != order.id,
            )
        ).all()
        if all(other.status == "DELIVERED" for other in other_orders):
            group.status = "COMPLETED"
    _record_outbox(db, event_name, {"order_id": order.id, "group_id": group.id})
    db.commit()
    db.refresh(order)
    return ok(_order_payload(db, order))

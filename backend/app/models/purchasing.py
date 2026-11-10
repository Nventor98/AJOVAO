from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PurchaseGroup(Base):
    __tablename__ = "purchase_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_id: Mapped[str] = mapped_column(ForeignKey("communities.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    basket_id: Mapped[str | None] = mapped_column(ForeignKey("standing_baskets.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    area: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False, index=True)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    delivery_method: Mapped[str] = mapped_column(String(32), nullable=False)
    collection_point_id: Mapped[str | None] = mapped_column(ForeignKey("collection_points.id"), nullable=True)
    minimum_households: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_quotation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("minimum_households IS NULL OR minimum_households > 0", name="ck_purchase_group_min_households_positive"),
        CheckConstraint("delivery_method IN ('collection_point', 'doorstep')", name="ck_purchase_group_delivery_method"),
    )


class PurchaseGroupTarget(Base):
    __tablename__ = "purchase_group_targets"
    __table_args__ = (
        UniqueConstraint("group_id", "product_id", "grade_id", "unit_id", name="uq_purchase_group_target_sku"),
        CheckConstraint("minimum_quantity IS NULL OR minimum_quantity > 0", name="ck_purchase_target_minimum_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(ForeignKey("purchase_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    grade_id: Mapped[str] = mapped_column(ForeignKey("product_grades.id"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    minimum_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)


class PurchaseGroupMember(Base):
    __tablename__ = "purchase_group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_purchase_group_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(ForeignKey("purchase_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (
        UniqueConstraint("group_id", "target_id", "member_id", name="uq_purchase_request_member_target"),
        CheckConstraint("quantity > 0", name="ck_purchase_request_quantity_positive"),
        Index("ix_purchase_requests_group_status", "group_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(ForeignKey("purchase_groups.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("purchase_group_targets.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    placed_by_agent_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    consent_id: Mapped[str | None] = mapped_column(ForeignKey("agent_consents.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(24), default="app", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupplierQuotation(Base):
    __tablename__ = "supplier_quotations"
    __table_args__ = (
        UniqueConstraint("group_id", "supplier_id", name="uq_supplier_quotation_group_supplier"),
        CheckConstraint("delivery_fee_kobo >= 0 AND handling_fee_kobo >= 0 AND other_fees_kobo >= 0", name="ck_quotation_fees_nonnegative"),
        CheckConstraint("total_delivered_kobo >= 0", name="ck_quotation_total_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(ForeignKey("purchase_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    delivery_fee_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    handling_fee_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    other_fees_kobo: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_delivered_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SupplierQuotationItem(Base):
    __tablename__ = "supplier_quotation_items"
    __table_args__ = (
        UniqueConstraint("quotation_id", "target_id", name="uq_quotation_item_target"),
        CheckConstraint("unit_price_kobo >= 0 AND offered_quantity > 0", name="ck_quotation_item_values_valid"),
        CheckConstraint("line_total_kobo >= 0", name="ck_quotation_item_total_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    quotation_id: Mapped[str] = mapped_column(ForeignKey("supplier_quotations.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("purchase_group_targets.id"), nullable=False)
    offered_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_price_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_total_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("group_id", "member_id", name="uq_purchase_order_group_member"),
        CheckConstraint("total_amount_kobo >= 0", name="ck_purchase_order_amount_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    group_id: Mapped[str] = mapped_column(ForeignKey("purchase_groups.id"), nullable=False, index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    quotation_id: Mapped[str] = mapped_column(ForeignKey("supplier_quotations.id"), nullable=False)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_PAYMENT", nullable=False, index=True)
    delivery_method: Mapped[str] = mapped_column(String(32), nullable=False)
    subtotal_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delivery_fee_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    handling_fee_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    other_fees_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_order_item_request_once"),
        CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),
        CheckConstraint("unit_price_kobo >= 0 AND line_total_kobo >= 0", name="ck_order_item_prices_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("purchase_requests.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("purchase_group_targets.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_price_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_total_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    baseline_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("baseline_snapshots.id"), nullable=True)


class StandingBasket(Base):
    __tablename__ = "standing_baskets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_id: Mapped[str] = mapped_column(ForeignKey("communities.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    area: Mapped[str] = mapped_column(String(160), nullable=False)
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    cutoff_after_days: Mapped[int] = mapped_column(Integer, nullable=False)
    cycle_anchor_day: Mapped[int] = mapped_column(Integer, nullable=False)
    next_cycle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    delivery_method: Mapped[str] = mapped_column(String(32), nullable=False)
    collection_point_id: Mapped[str | None] = mapped_column(ForeignKey("collection_points.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("cadence IN ('weekly', 'monthly')", name="ck_basket_cadence"),
        CheckConstraint("cutoff_after_days > 0", name="ck_basket_cutoff_positive"),
        CheckConstraint("cycle_anchor_day BETWEEN 1 AND 31", name="ck_basket_anchor_day"),
        CheckConstraint("delivery_method IN ('collection_point', 'doorstep')", name="ck_basket_delivery_method"),
    )


class StandingBasketTarget(Base):
    __tablename__ = "standing_basket_targets"
    __table_args__ = (
        UniqueConstraint("basket_id", "product_id", "grade_id", "unit_id", name="uq_basket_target_sku"),
        CheckConstraint("quantity > 0", name="ck_basket_target_quantity_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    basket_id: Mapped[str] = mapped_column(ForeignKey("standing_baskets.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    grade_id: Mapped[str] = mapped_column(ForeignKey("product_grades.id"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)


class StandingBasketSubscription(Base):
    __tablename__ = "standing_basket_subscriptions"
    __table_args__ = (UniqueConstraint("basket_id", "user_id", name="uq_basket_subscription_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    basket_id: Mapped[str] = mapped_column(ForeignKey("standing_baskets.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StandingBasketCycle(Base):
    __tablename__ = "standing_basket_cycles"
    __table_args__ = (UniqueConstraint("basket_id", "cycle_start", name="uq_basket_cycle_start"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    basket_id: Mapped[str] = mapped_column(ForeignKey("standing_baskets.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_group_id: Mapped[str] = mapped_column(ForeignKey("purchase_groups.id"), nullable=False, unique=True)
    cycle_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cycle_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class StandingBasketParticipation(Base):
    __tablename__ = "standing_basket_participations"
    __table_args__ = (UniqueConstraint("cycle_id", "user_id", name="uq_basket_cycle_participant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cycle_id: Mapped[str] = mapped_column(ForeignKey("standing_basket_cycles.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="OPTED_IN", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

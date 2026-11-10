from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PointGeometry


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("product_categories.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    dimension: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    to_base_factor: Mapped[Decimal] = mapped_column(Numeric(20, 9), nullable=False)

    __table_args__ = (
        CheckConstraint("to_base_factor > 0", name="ck_unit_positive_factor"),
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ProductGrade(Base):
    __tablename__ = "product_grades"
    __table_args__ = (
        UniqueConstraint("product_id", "code", name="uq_product_grade_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    business_name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    scorecard_publication_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    area: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), default="NG", nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    location: Mapped[str | None] = mapped_column(PointGeometry(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class SupplierDocument(Base):
    __tablename__ = "supplier_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class SupplierInventory(Base):
    __tablename__ = "supplier_inventory"
    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id", "grade_id", "unit_id", name="uq_supplier_inventory_sku"),
        CheckConstraint("quantity >= 0", name="ck_inventory_nonnegative_quantity"),
        CheckConstraint("unit_price_kobo >= 0", name="ck_inventory_nonnegative_price"),
        Index("ix_supplier_inventory_product_grade", "product_id", "grade_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    grade_id: Mapped[str] = mapped_column(ForeignKey("product_grades.id"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_price_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    supply_lot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    inventory_id: Mapped[str] = mapped_column(ForeignKey("supplier_inventory.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        CheckConstraint("unit_price_kobo >= 0", name="ck_price_observation_nonnegative_price"),
        Index("ix_price_observations_comparison", "product_id", "grade_id", "unit_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    grade_id: Mapped[str] = mapped_column(ForeignKey("product_grades.id"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    unit_price_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    area: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    location: Mapped[str | None] = mapped_column(PointGeometry(), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    recorded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    anomaly_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class BaselineSnapshot(Base):
    __tablename__ = "baseline_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    grade_id: Mapped[str] = mapped_column(ForeignKey("product_grades.id"), nullable=False)
    requested_unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    area: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    observation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_unit_price_kobo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline_total_kobo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oldest_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    newest_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PriceIndexEntry(Base):
    __tablename__ = "price_index_entries"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "grade_id", "unit_id", "area", "period_start", "period_end",
            name="uq_price_index_period",
        ),
        CheckConstraint("sample_size >= 0", name="ck_price_index_sample_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    grade_id: Mapped[str] = mapped_column(ForeignKey("product_grades.id"), nullable=False)
    unit_id: Mapped[str] = mapped_column(ForeignKey("units.id"), nullable=False)
    area: Mapped[str] = mapped_column(String(160), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    median_unit_price_kobo: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    observation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SupplierScorecardData(Base):
    __tablename__ = "supplier_scorecard_data"

    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), primary_key=True)
    deliveries_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deliveries_successful: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grade_checks_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grade_checks_accurate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disputes_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deliveries_on_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

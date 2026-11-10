from __future__ import annotations

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
from app.db.types import point_wkt
from app.deps.auth import CurrentUserDependency
from app.models.catalogue import (
    InventoryMovement,
    PriceIndexEntry,
    PriceObservation,
    Product,
    ProductCategory,
    ProductGrade,
    Supplier,
    SupplierDocument,
    SupplierInventory,
    SupplierScorecardData,
    Unit,
)
from app.models.user import User
from app.shared.audit import record_audit
from app.shared.permissions import Role, require_roles
from app.shared.responses import ok
from app.services.pricing import comparison_candidates, create_baseline_snapshot as build_baseline_snapshot

router = APIRouter(prefix="/api/v1", tags=["catalogue and pricing"])
Db = Annotated[Session, Depends(get_db)]
PriceSourceType = Literal["retail", "wholesale", "farm_gate", "market"]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: str | None = None


class UnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=24, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    dimension: str = Field(min_length=1, max_length=24)
    to_base_factor: Decimal = Field(gt=0, max_digits=20, decimal_places=9)


class GradeInput(BaseModel):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ProductCreate(BaseModel):
    category_id: str
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=2000)
    base_unit_id: str
    grades: list[GradeInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_grade_codes(self) -> "ProductCreate":
        codes = [grade.code.lower() for grade in self.grades]
        if len(set(codes)) != len(codes):
            raise ValueError("Grade codes must be unique within a product.")
        return self


class SupplierCreate(BaseModel):
    business_name: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, max_length=255)
    area: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country_code: str = Field(default="NG", pattern=r"^[A-Z]{2}$")
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "SupplierCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return self


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    address: str | None = Field(default=None, max_length=255)
    area: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)

    @model_validator(mode="after")
    def coordinates_are_updated_as_a_pair(self) -> "SupplierUpdate":
        fields = self.model_fields_set
        if ("latitude" in fields) != ("longitude" in fields):
            raise ValueError("Latitude and longitude must be updated together.")
        return self


class SupplierDocumentCreate(BaseModel):
    document_type: str = Field(min_length=2, max_length=60)
    storage_key: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9/_\-.]*$")

    @model_validator(mode="after")
    def storage_key_is_private_relative_reference(self) -> "SupplierDocumentCreate":
        if self.storage_key.startswith("/") or "\\" in self.storage_key:
            raise ValueError("Storage key must be a private relative object reference.")
        if any(part in {"", ".", ".."} for part in self.storage_key.split("/")):
            raise ValueError("Storage key must be a private relative object reference.")
        return self


class SupplierVerification(BaseModel):
    status: Literal["VERIFIED", "REJECTED", "SUSPENDED"]


class InventoryUpdate(BaseModel):
    product_id: str
    grade_id: str
    unit_id: str
    quantity_delta: Decimal = Field(max_digits=20, decimal_places=6)
    unit_price_kobo: int = Field(ge=0)
    reason: str = Field(min_length=2, max_length=80)
    supply_lot_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def movement_must_be_nonzero(self) -> "InventoryUpdate":
        if self.quantity_delta == 0:
            raise ValueError("Inventory movement must be non-zero.")
        return self


class PriceObservationCreate(BaseModel):
    product_id: str
    grade_id: str
    unit_id: str
    unit_price_kobo: int = Field(ge=0)
    source_type: PriceSourceType
    source_name: str = Field(min_length=2, max_length=160)
    area: str = Field(min_length=1, max_length=160)
    observed_at: datetime
    supplier_id: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)

    @model_validator(mode="after")
    def validate_observation(self) -> "PriceObservationCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Observation timestamp must include a timezone.")
        if self.observed_at > datetime.now(timezone.utc):
            raise ValueError("Observation timestamp cannot be in the future.")
        return self




class BaselineRequest(BaseModel):
    product_id: str
    grade_id: str
    unit_id: str
    area: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=10, decimal_places=7)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=10, decimal_places=7)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "BaselineRequest":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return self


class PriceIndexPublish(BaseModel):
    product_id: str
    grade_id: str
    unit_id: str
    area: str = Field(min_length=1, max_length=160)
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def validate_period(self) -> "PriceIndexPublish":
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("Index period timestamps must include a timezone.")
        if self.period_start >= self.period_end or self.period_end > datetime.now(timezone.utc):
            raise ValueError("Index period is invalid.")
        return self


class ScorecardUpdate(BaseModel):
    deliveries_total: int = Field(ge=0)
    deliveries_successful: int = Field(ge=0)
    grade_checks_total: int = Field(ge=0)
    grade_checks_accurate: int = Field(ge=0)
    disputes_total: int = Field(ge=0)
    deliveries_on_time: int = Field(ge=0)

    @model_validator(mode="after")
    def counters_are_consistent(self) -> "ScorecardUpdate":
        if self.deliveries_successful > self.deliveries_total:
            raise ValueError("Successful deliveries cannot exceed total deliveries.")
        if self.deliveries_on_time > self.deliveries_total:
            raise ValueError("On-time deliveries cannot exceed total deliveries.")
        if self.grade_checks_accurate > self.grade_checks_total:
            raise ValueError("Accurate grade checks cannot exceed total grade checks.")
        if self.disputes_total > self.deliveries_total:
            raise ValueError("Disputes cannot exceed total deliveries.")
        return self


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _staff_or_admin(user: object) -> bool:
    roles = set(getattr(user, "roles", []) or [])
    return bool(roles.intersection({Role.ADMIN.value, Role.STAFF.value}))


def _require_staff(user: object) -> None:
    require_roles(user, Role.ADMIN, Role.STAFF)


def _check_product_grade_unit(
    db: Session,
    *,
    product_id: str,
    grade_id: str,
    unit_id: str,
) -> tuple[Product, ProductGrade, Unit]:
    product = db.get(Product, product_id)
    grade = db.get(ProductGrade, grade_id)
    unit = db.get(Unit, unit_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Product not found.")
    if grade is None or not grade.is_active or grade.product_id != product_id:
        raise HTTPException(status_code=422, detail="Grade does not belong to the selected product.")
    base_unit = db.get(Unit, product.base_unit_id)
    if unit is None or base_unit is None or unit.dimension != base_unit.dimension:
        raise HTTPException(status_code=422, detail="Unit is not compatible with this product.")
    return product, grade, unit


def _supplier_for_user(db: Session, user_id: str) -> Supplier | None:
    return db.scalar(select(Supplier).where(Supplier.user_id == user_id))


def _require_supplier_owner_or_staff(supplier: Supplier, current_user: object) -> None:
    if getattr(current_user, "user_id", None) != supplier.user_id and not _staff_or_admin(current_user):
        raise HTTPException(status_code=403, detail="Supplier owner access required.")


def _supplier_payload(supplier: Supplier) -> dict:
    return {
        "id": supplier.id,
        "business_name": supplier.business_name,
        "description": supplier.description,
        "verification_status": supplier.verification_status,
        "is_verified": supplier.verification_status == "VERIFIED",
        "address": supplier.address,
        "area": supplier.area,
        "city": supplier.city,
        "state": supplier.state,
        "country_code": supplier.country_code,
        "latitude": supplier.latitude,
        "longitude": supplier.longitude,
    }


def _product_payload(db: Session, product: Product) -> dict:
    category = db.get(ProductCategory, product.category_id)
    unit = db.get(Unit, product.base_unit_id)
    grades = db.scalars(
        select(ProductGrade)
        .where(ProductGrade.product_id == product.id, ProductGrade.is_active.is_(True))
        .order_by(ProductGrade.name)
    ).all()
    return {
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "description": product.description,
        "category": {"id": category.id, "name": category.name, "slug": category.slug} if category else None,
        "base_unit": {"id": unit.id, "code": unit.code, "name": unit.name, "dimension": unit.dimension} if unit else None,
        "grades": [{"id": grade.id, "code": grade.code, "name": grade.name, "description": grade.description} for grade in grades],
    }


def _observation_payload(observation: PriceObservation) -> dict:
    now = datetime.now(timezone.utc)
    observed_at = _aware(observation.observed_at)
    return {
        "id": observation.id,
        "product_id": observation.product_id,
        "grade_id": observation.grade_id,
        "unit_id": observation.unit_id,
        "unit_price_kobo": observation.unit_price_kobo,
        "source_type": observation.source_type,
        "source_name": observation.source_name,
        "area": observation.area,
        "observed_at": observed_at,
        "is_stale": observed_at < now - timedelta(days=settings.price_observation_max_age_days),
        "is_anomaly": observation.is_anomaly,
        "anomaly_reason": observation.anomaly_reason,
    }


@router.get("/product-categories")
def list_categories(db: Db) -> dict:
    categories = db.scalars(
        select(ProductCategory).where(ProductCategory.is_active.is_(True)).order_by(ProductCategory.name)
    ).all()
    return ok([{"id": item.id, "name": item.name, "slug": item.slug, "parent_id": item.parent_id} for item in categories])


@router.post("/product-categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, current_user: CurrentUserDependency, db: Db) -> dict:
    _require_staff(current_user)
    if payload.parent_id is not None and db.get(ProductCategory, payload.parent_id) is None:
        raise HTTPException(status_code=422, detail="Parent category does not exist.")
    category = ProductCategory(**payload.model_dump())
    db.add(category)
    record_audit(db, action="catalogue.category_created", actor_id=current_user.user_id, entity_type="product_category", entity_id=category.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Category name or slug already exists.") from exc
    return ok({"id": category.id, "name": category.name, "slug": category.slug})


@router.get("/units")
def list_units(db: Db) -> dict:
    units = db.scalars(select(Unit).order_by(Unit.dimension, Unit.code)).all()
    return ok(
        [
            {
                "id": unit.id,
                "code": unit.code,
                "name": unit.name,
                "dimension": unit.dimension,
                "to_base_factor": str(unit.to_base_factor),
            }
            for unit in units
        ]
    )


@router.post("/units", status_code=status.HTTP_201_CREATED)
def create_unit(payload: UnitCreate, current_user: CurrentUserDependency, db: Db) -> dict:
    _require_staff(current_user)
    unit = Unit(**payload.model_dump())
    db.add(unit)
    record_audit(db, action="catalogue.unit_created", actor_id=current_user.user_id, entity_type="unit", entity_id=unit.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unit code or name already exists.") from exc
    return ok({"id": unit.id, "code": unit.code, "name": unit.name, "dimension": unit.dimension})


@router.get("/products")
def list_products(
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category_id: str | None = None,
    search: str | None = Query(default=None, max_length=100),
) -> dict:
    query = select(Product).where(Product.is_active.is_(True))
    if category_id:
        query = query.where(Product.category_id == category_id)
    if search:
        query = query.where(Product.name.ilike(f"%{search.strip()}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    products = db.scalars(query.order_by(Product.name).offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [_product_payload(db, product) for product in products],
        meta={"pagination": {"page": page, "page_size": page_size, "total": total}},
    )


@router.post("/products", status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, current_user: CurrentUserDependency, db: Db) -> dict:
    _require_staff(current_user)
    category = db.get(ProductCategory, payload.category_id)
    unit = db.get(Unit, payload.base_unit_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=422, detail="Product category does not exist.")
    if unit is None:
        raise HTTPException(status_code=422, detail="Base unit does not exist.")
    product = Product(
        category_id=payload.category_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        base_unit_id=payload.base_unit_id,
        created_by=current_user.user_id,
    )
    db.add(product)
    db.flush()
    for grade_data in payload.grades:
        db.add(ProductGrade(product_id=product.id, **grade_data.model_dump()))
    record_audit(db, action="catalogue.product_created", actor_id=current_user.user_id, entity_type="product", entity_id=product.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Product slug or grade already exists.") from exc
    return ok(_product_payload(db, product))


@router.get("/products/{product_id}")
def get_product(product_id: str, db: Db) -> dict:
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Product not found.")
    return ok(_product_payload(db, product))


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
def create_supplier(payload: SupplierCreate, current_user: CurrentUserDependency, db: Db) -> dict:
    existing = _supplier_for_user(db, current_user.user_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="A supplier profile already exists for this account.")
    fields = payload.model_dump()
    latitude, longitude = fields["latitude"], fields["longitude"]
    supplier = Supplier(
        user_id=current_user.user_id,
        **fields,
        location=point_wkt(float(latitude), float(longitude)) if latitude is not None else None,
    )
    db.add(supplier)
    user = db.get(User, current_user.user_id)
    if user is not None:
        user.roles = list(set(user.roles or []).union({Role.SUPPLIER.value}))
    record_audit(db, action="supplier.registered", actor_id=current_user.user_id, entity_type="supplier", entity_id=supplier.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A supplier profile already exists for this account.") from exc
    return ok(_supplier_payload(supplier))


@router.get("/suppliers")
def list_suppliers(
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    area: str | None = None,
) -> dict:
    query = select(Supplier).where(Supplier.verification_status == "VERIFIED")
    if area:
        query = query.where(func.lower(Supplier.area) == area.strip().lower())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    suppliers = db.scalars(query.order_by(Supplier.business_name).offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [_supplier_payload(supplier) for supplier in suppliers],
        meta={"pagination": {"page": page, "page_size": page_size, "total": total}},
    )


@router.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    if supplier.verification_status != "VERIFIED":
        _require_supplier_owner_or_staff(supplier, current_user)
    return ok(_supplier_payload(supplier))


@router.patch("/suppliers/{supplier_id}")
def update_supplier(
    supplier_id: str,
    payload: SupplierUpdate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    _require_supplier_owner_or_staff(supplier, current_user)
    fields = payload.model_dump(exclude_unset=True)
    latitude = fields.get("latitude", supplier.latitude)
    longitude = fields.get("longitude", supplier.longitude)
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=422, detail="Latitude and longitude must be supplied together.")
    for field, value in fields.items():
        setattr(supplier, field, value)
    supplier.location = point_wkt(float(latitude), float(longitude)) if latitude is not None else None
    record_audit(
        db,
        action="supplier.profile_updated",
        actor_id=current_user.user_id,
        entity_type="supplier",
        entity_id=supplier.id,
        details={"fields": sorted(fields)},
    )
    db.commit()
    return ok(_supplier_payload(supplier))


@router.post("/suppliers/{supplier_id}/verify")
def verify_supplier(
    supplier_id: str,
    payload: SupplierVerification,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    _require_staff(current_user)
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    supplier.verification_status = payload.status
    record_audit(
        db,
        action="supplier.verification_updated",
        actor_id=current_user.user_id,
        entity_type="supplier",
        entity_id=supplier.id,
        details={"status": payload.status},
    )
    db.commit()
    return ok({"id": supplier.id, "verification_status": supplier.verification_status})


@router.post("/suppliers/{supplier_id}/documents", status_code=status.HTTP_201_CREATED)
def add_supplier_document(
    supplier_id: str,
    payload: SupplierDocumentCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    _require_supplier_owner_or_staff(supplier, current_user)
    document = SupplierDocument(supplier_id=supplier.id, **payload.model_dump())
    db.add(document)
    record_audit(
        db,
        action="supplier.document_added",
        actor_id=current_user.user_id,
        entity_type="supplier_document",
        entity_id=document.id,
    )
    db.commit()
    return ok({"id": document.id, "document_type": document.document_type, "status": document.status})


@router.get("/suppliers/{supplier_id}/documents")
def list_supplier_documents(supplier_id: str, current_user: CurrentUserDependency, db: Db) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    _require_supplier_owner_or_staff(supplier, current_user)
    documents = db.scalars(
        select(SupplierDocument)
        .where(SupplierDocument.supplier_id == supplier_id)
        .order_by(SupplierDocument.uploaded_at.desc())
    ).all()
    return ok(
        [
            {
                "id": doc.id,
                "document_type": doc.document_type,
                "storage_key": doc.storage_key,
                "status": doc.status,
                "uploaded_at": doc.uploaded_at,
            }
            for doc in documents
        ]
    )


@router.post("/suppliers/{supplier_id}/inventory", status_code=status.HTTP_201_CREATED)
def update_inventory(
    supplier_id: str,
    payload: InventoryUpdate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    _require_supplier_owner_or_staff(supplier, current_user)
    if supplier.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail="Supplier verification is required to manage inventory.")
    _check_product_grade_unit(
        db,
        product_id=payload.product_id,
        grade_id=payload.grade_id,
        unit_id=payload.unit_id,
    )
    inventory = db.scalar(
        select(SupplierInventory)
        .where(
            SupplierInventory.supplier_id == supplier.id,
            SupplierInventory.product_id == payload.product_id,
            SupplierInventory.grade_id == payload.grade_id,
            SupplierInventory.unit_id == payload.unit_id,
        )
        .with_for_update()
    )
    if inventory is None:
        inventory = SupplierInventory(
            supplier_id=supplier.id,
            product_id=payload.product_id,
            grade_id=payload.grade_id,
            unit_id=payload.unit_id,
            quantity=Decimal("0"),
            unit_price_kobo=payload.unit_price_kobo,
            supply_lot_id=payload.supply_lot_id,
        )
        db.add(inventory)
        db.flush()
    quantity_after = Decimal(inventory.quantity) + payload.quantity_delta
    if quantity_after < 0:
        db.rollback()
        raise HTTPException(status_code=422, detail="Inventory quantity cannot become negative.")
    inventory.quantity = quantity_after
    inventory.unit_price_kobo = payload.unit_price_kobo
    inventory.supply_lot_id = payload.supply_lot_id
    movement = InventoryMovement(
        inventory_id=inventory.id,
        changed_by=current_user.user_id,
        quantity_delta=payload.quantity_delta,
        quantity_after=quantity_after,
        reason=payload.reason,
    )
    db.add(movement)
    record_audit(
        db,
        action="inventory.stock_received",
        actor_id=current_user.user_id,
        entity_type="supplier_inventory",
        entity_id=inventory.id,
        details={"quantity_delta": str(payload.quantity_delta), "quantity_after": str(quantity_after)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Inventory record already exists; retry the stock update.") from exc
    return ok(
        {
            "id": inventory.id,
            "supplier_id": supplier.id,
            "product_id": inventory.product_id,
            "grade_id": inventory.grade_id,
            "unit_id": inventory.unit_id,
            "quantity": str(inventory.quantity),
            "unit_price_kobo": inventory.unit_price_kobo,
            "supply_lot_id": inventory.supply_lot_id,
        }
    )


@router.get("/suppliers/{supplier_id}/inventory")
def list_inventory(
    supplier_id: str,
    current_user: CurrentUserDependency,
    db: Db,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    if supplier.verification_status != "VERIFIED":
        _require_supplier_owner_or_staff(supplier, current_user)
    query = select(SupplierInventory).where(SupplierInventory.supplier_id == supplier_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(SupplierInventory.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return ok(
        [
            {
                "id": row.id,
                "product_id": row.product_id,
                "grade_id": row.grade_id,
                "unit_id": row.unit_id,
                "quantity": str(row.quantity),
                "unit_price_kobo": row.unit_price_kobo,
                "supply_lot_id": row.supply_lot_id,
                "is_verified_supplier": supplier.verification_status == "VERIFIED",
            }
            for row in rows
        ],
        meta={"pagination": {"page": page, "page_size": page_size, "total": total}},
    )


@router.post("/price-observations", status_code=status.HTTP_201_CREATED)
def create_price_observation(
    payload: PriceObservationCreate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    _check_product_grade_unit(
        db,
        product_id=payload.product_id,
        grade_id=payload.grade_id,
        unit_id=payload.unit_id,
    )
    supplier = _supplier_for_user(db, current_user.user_id)
    if not _staff_or_admin(current_user):
        if supplier is None or supplier.verification_status != "VERIFIED":
            raise HTTPException(status_code=403, detail="Verified supplier or staff access required.")
        if payload.source_type not in {"retail", "wholesale"} or payload.supplier_id not in {None, supplier.id}:
            raise HTTPException(status_code=403, detail="Suppliers may only submit their own retail or wholesale prices.")
        supplier_id = supplier.id
        source_name = supplier.business_name
    else:
        supplier_id = payload.supplier_id
        source_name = payload.source_name.strip()
        if supplier_id is not None and db.get(Supplier, supplier_id) is None:
            raise HTTPException(status_code=422, detail="Supplier does not exist.")

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.price_observation_max_age_days)
    recent = db.scalars(
        select(PriceObservation)
        .where(
            PriceObservation.product_id == payload.product_id,
            PriceObservation.grade_id == payload.grade_id,
            PriceObservation.unit_id == payload.unit_id,
            PriceObservation.area == payload.area,
            PriceObservation.source_type != "farm_gate",
            PriceObservation.is_anomaly.is_(False),
            PriceObservation.observed_at >= cutoff,
        )
        .order_by(PriceObservation.observed_at.desc())
        .limit(21)
    ).all()
    valid_prices = sorted(item.unit_price_kobo for item in recent)
    is_anomaly = False
    reason = None
    if len(valid_prices) >= 3:
        median = Decimal(valid_prices[len(valid_prices) // 2]) if len(valid_prices) % 2 else (
            Decimal(valid_prices[len(valid_prices) // 2 - 1] + valid_prices[len(valid_prices) // 2]) / 2
        )
        if median > 0 and (
            Decimal(payload.unit_price_kobo) > median * settings.price_anomaly_ratio
            or Decimal(payload.unit_price_kobo) * settings.price_anomaly_ratio < median
        ):
            is_anomaly = True
            reason = "Price differs from recent comparable median beyond configured ratio."

    observation = PriceObservation(
        product_id=payload.product_id,
        grade_id=payload.grade_id,
        unit_id=payload.unit_id,
        unit_price_kobo=payload.unit_price_kobo,
        source_type=payload.source_type,
        source_name=source_name,
        supplier_id=supplier_id,
        area=payload.area.strip(),
        latitude=payload.latitude,
        longitude=payload.longitude,
        location=point_wkt(float(payload.latitude), float(payload.longitude)) if payload.latitude is not None else None,
        observed_at=payload.observed_at.astimezone(timezone.utc),
        recorded_by=current_user.user_id,
        is_anomaly=is_anomaly,
        anomaly_reason=reason,
    )
    db.add(observation)
    record_audit(
        db,
        action="price_observation.recorded",
        actor_id=current_user.user_id,
        entity_type="price_observation",
        entity_id=observation.id,
        details={"source_type": observation.source_type, "is_anomaly": is_anomaly},
    )
    db.commit()
    return ok(_observation_payload(observation))


@router.get("/products/{product_id}/prices")
def list_product_prices(
    product_id: str,
    db: Db,
    grade_id: str | None = None,
    area: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    query = select(PriceObservation).where(PriceObservation.product_id == product_id)
    if grade_id:
        query = query.where(PriceObservation.grade_id == grade_id)
    if area:
        query = query.where(func.lower(PriceObservation.area) == area.strip().lower())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    observations = db.scalars(
        query.order_by(PriceObservation.observed_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok(
        [_observation_payload(item) for item in observations],
        meta={"pagination": {"page": page, "page_size": page_size, "total": total}},
    )


@router.get("/prices/compare")
def compare_prices(
    product_id: str,
    grade_id: str,
    unit_id: str,
    area: str,
    db: Db,
    latitude: Decimal | None = Query(default=None, ge=-90, le=90),
    longitude: Decimal | None = Query(default=None, ge=-180, le=180),
    max_age_days: int = Query(default=settings.savings_baseline_max_age_days, ge=1, le=365),
) -> dict:
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=422, detail="Latitude and longitude must be supplied together.")
    _, _, unit = _check_product_grade_unit(db, product_id=product_id, grade_id=grade_id, unit_id=unit_id)
    candidates = comparison_candidates(
        db,
        product_id=product_id,
        grade_id=grade_id,
        requested_unit=unit,
        area=area,
        latitude=latitude,
        longitude=longitude,
        max_age_days=max_age_days,
    )
    prices = sorted(price for _, _, price in candidates)
    median = None
    if prices:
        middle = len(prices) // 2
        median = prices[middle] if len(prices) % 2 else int(
            (Decimal(prices[middle - 1] + prices[middle]) / 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    observation_ids = [observation.id for observation, _, _ in candidates]
    return ok(
        {
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": unit.id,
            "area": area,
            "currency": "NGN",
            "unit_price_kobo": median,
            "sample_size": len(candidates),
            "source_count": len({observation.source_name.casefold() for observation, _, _ in candidates}),
            "observation_ids": observation_ids,
            "prices": [
                {
                    **_observation_payload(observation),
                    "comparable_unit_price_kobo": comparable_price,
                    "comparable_unit_id": unit.id,
                }
                for observation, _, comparable_price in candidates
            ],
        }
    )


@router.post("/prices/baseline-snapshots", status_code=status.HTTP_201_CREATED)
def create_baseline_snapshot(
    payload: BaselineRequest,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    product, grade, requested_unit = _check_product_grade_unit(
        db,
        product_id=payload.product_id,
        grade_id=payload.grade_id,
        unit_id=payload.unit_id,
    )
    snapshot = build_baseline_snapshot(
        db,
        product=product,
        grade=grade,
        requested_unit=requested_unit,
        area=payload.area,
        latitude=payload.latitude,
        longitude=payload.longitude,
        quantity=payload.quantity,
        created_by=current_user.user_id,
    )
    db.add(snapshot)
    record_audit(
        db,
        action="price.baseline_snapshot_created",
        actor_id=current_user.user_id,
        entity_type="baseline_snapshot",
        entity_id=snapshot.id,
        details={"status": snapshot.status, "sample_size": snapshot.sample_size, "reason": snapshot.reason},
    )
    db.commit()
    return ok(
        {
            "id": snapshot.id,
            "status": snapshot.status,
            "reason": snapshot.reason,
            "method": snapshot.method,
            "observation_ids": snapshot.observation_ids,
            "sample_size": snapshot.sample_size,
            "source_count": snapshot.source_count,
            "baseline_unit_price_kobo": snapshot.baseline_unit_price_kobo,
            "baseline_total_kobo": snapshot.baseline_total_kobo,
            "oldest_observed_at": snapshot.oldest_observed_at,
            "newest_observed_at": snapshot.newest_observed_at,
            "area": snapshot.area,
            "currency": "NGN",
        }
    )


@router.get("/price-index")
def list_price_index(
    db: Db,
    product_id: str | None = None,
    grade_id: str | None = None,
    unit_id: str | None = None,
    area: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    query = select(PriceIndexEntry).where(PriceIndexEntry.published_at.is_not(None))
    if product_id:
        query = query.where(PriceIndexEntry.product_id == product_id)
    if grade_id:
        query = query.where(PriceIndexEntry.grade_id == grade_id)
    if unit_id:
        query = query.where(PriceIndexEntry.unit_id == unit_id)
    if area:
        query = query.where(func.lower(PriceIndexEntry.area) == area.strip().lower())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    entries = db.scalars(
        query.order_by(PriceIndexEntry.published_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok(
        [
            {
                "id": item.id,
                "product_id": item.product_id,
                "grade_id": item.grade_id,
                "unit_id": item.unit_id,
                "area": item.area,
                "period_start": item.period_start,
                "period_end": item.period_end,
                "median_unit_price_kobo": item.median_unit_price_kobo,
                "sample_size": item.sample_size,
                "source_count": item.source_count,
                "sources": item.source_names,
                "published_at": item.published_at,
            }
            for item in entries
        ],
        meta={"pagination": {"page": page, "page_size": page_size, "total": total}},
    )


@router.post("/price-index/publish", status_code=status.HTTP_201_CREATED)
def publish_price_index(
    payload: PriceIndexPublish,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    _require_staff(current_user)
    _check_product_grade_unit(
        db,
        product_id=payload.product_id,
        grade_id=payload.grade_id,
        unit_id=payload.unit_id,
    )
    start = payload.period_start.astimezone(timezone.utc)
    end = payload.period_end.astimezone(timezone.utc)
    observations = db.scalars(
        select(PriceObservation).where(
            PriceObservation.product_id == payload.product_id,
            PriceObservation.grade_id == payload.grade_id,
            PriceObservation.unit_id == payload.unit_id,
            func.lower(PriceObservation.area) == payload.area.strip().lower(),
            PriceObservation.source_type != "farm_gate",
            PriceObservation.is_anomaly.is_(False),
            PriceObservation.observed_at >= start,
            PriceObservation.observed_at <= end,
        )
    ).all()
    by_source: dict[str, PriceObservation] = {}
    for observation in sorted(observations, key=lambda item: _aware(item.observed_at)):
        by_source.setdefault(observation.source_name.casefold(), observation)
    chosen = list(by_source.values())
    if len(observations) < settings.price_index_min_samples or len(chosen) < settings.price_index_min_sources:
        raise HTTPException(
            status_code=422,
            detail="Price index cannot be published below configured sample and independent-source minimums.",
        )
    prices = sorted(item.unit_price_kobo for item in observations)
    middle = len(prices) // 2
    median = prices[middle] if len(prices) % 2 else int(
        (Decimal(prices[middle - 1] + prices[middle]) / 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    entry = PriceIndexEntry(
        product_id=payload.product_id,
        grade_id=payload.grade_id,
        unit_id=payload.unit_id,
        area=payload.area.strip(),
        period_start=start,
        period_end=end,
        median_unit_price_kobo=median,
        sample_size=len(observations),
        source_count=len(chosen),
        source_names=sorted(by_source),
        observation_ids=[item.id for item in observations],
        published_at=datetime.now(timezone.utc),
        published_by=current_user.user_id,
        created_by=current_user.user_id,
    )
    db.add(entry)
    record_audit(
        db,
        action="price_index.published",
        actor_id=current_user.user_id,
        entity_type="price_index_entry",
        entity_id=entry.id,
        details={"sample_size": entry.sample_size, "source_count": entry.source_count},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This price-index period has already been published.") from exc
    return ok({"id": entry.id, "median_unit_price_kobo": entry.median_unit_price_kobo, "sample_size": entry.sample_size, "source_count": entry.source_count})


@router.post("/suppliers/{supplier_id}/scorecard-consent")
def set_scorecard_consent(
    supplier_id: str,
    accept: bool,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    _require_supplier_owner_or_staff(supplier, current_user)
    if supplier.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Only the supplier can grant or revoke scorecard publication consent.")
    supplier.scorecard_publication_consent_at = datetime.now(timezone.utc) if accept else None
    record_audit(
        db,
        action="supplier.scorecard_consent_updated",
        actor_id=current_user.user_id,
        entity_type="supplier",
        entity_id=supplier.id,
        details={"accepted": accept},
    )
    db.commit()
    return ok({"supplier_id": supplier.id, "accepted": accept})


@router.put("/suppliers/{supplier_id}/scorecard/data")
def update_scorecard_data(
    supplier_id: str,
    payload: ScorecardUpdate,
    current_user: CurrentUserDependency,
    db: Db,
) -> dict:
    _require_staff(current_user)
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    data = db.get(SupplierScorecardData, supplier_id)
    if data is None:
        data = SupplierScorecardData(supplier_id=supplier_id, **payload.model_dump())
        db.add(data)
    else:
        for field, value in payload.model_dump().items():
            setattr(data, field, value)
    record_audit(
        db,
        action="supplier.scorecard_data_updated",
        actor_id=current_user.user_id,
        entity_type="supplier_scorecard_data",
        entity_id=supplier_id,
    )
    db.commit()
    return ok({"supplier_id": supplier_id, "updated": True})


@router.get("/suppliers/{supplier_id}/scorecard")
def get_supplier_scorecard(supplier_id: str, db: Db) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    if supplier.verification_status != "VERIFIED" or supplier.scorecard_publication_consent_at is None:
        raise HTTPException(status_code=404, detail="Supplier scorecard is not publicly available.")
    data = db.get(SupplierScorecardData, supplier_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Supplier scorecard is not available.")

    def rate(numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return round(numerator / denominator, 4)

    return ok(
        {
            "supplier_id": supplier.id,
            "delivery_success_rate": rate(data.deliveries_successful, data.deliveries_total),
            "grade_accuracy_rate": rate(data.grade_checks_accurate, data.grade_checks_total),
            "on_time_rate": rate(data.deliveries_on_time, data.deliveries_total),
            "dispute_rate": rate(data.disputes_total, data.deliveries_total),
            "sample_sizes": {
                "deliveries": data.deliveries_total,
                "grade_checks": data.grade_checks_total,
            },
            "updated_at": data.updated_at,
        }
    )

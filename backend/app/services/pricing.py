from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.catalogue import BaselineSnapshot, PriceObservation, Product, ProductGrade, Unit


def aware_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _distance_km(lat1: Decimal, lon1: Decimal, lat2: Decimal, lon2: Decimal) -> float:
    lat1_r, lat2_r = radians(float(lat1)), radians(float(lat2))
    delta_lat = lat2_r - lat1_r
    delta_lon = radians(float(lon2 - lon1))
    value = sin(delta_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(value))


def _converted_price(observation: PriceObservation, source_unit: Unit, requested_unit: Unit) -> int:
    converted = (
        Decimal(observation.unit_price_kobo)
        * Decimal(requested_unit.to_base_factor)
        / Decimal(source_unit.to_base_factor)
    )
    return int(converted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def comparison_candidates(
    db: Session,
    *,
    product_id: str,
    grade_id: str,
    requested_unit: Unit,
    area: str,
    latitude: Decimal | None,
    longitude: Decimal | None,
    max_age_days: int,
) -> list[tuple[PriceObservation, Unit, int]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    observations = db.scalars(
        select(PriceObservation)
        .join(Unit, Unit.id == PriceObservation.unit_id)
        .where(
            PriceObservation.product_id == product_id,
            PriceObservation.grade_id == grade_id,
            Unit.dimension == requested_unit.dimension,
            PriceObservation.source_type != "farm_gate",
            PriceObservation.is_anomaly.is_(False),
            PriceObservation.observed_at >= cutoff,
        )
        .order_by(PriceObservation.observed_at.desc())
    ).all()
    candidates: list[tuple[PriceObservation, Unit, int]] = []
    for observation in observations:
        source_unit = db.get(Unit, observation.unit_id)
        if source_unit is None:
            continue
        if latitude is None:
            if observation.area.casefold() != area.casefold():
                continue
        else:
            if observation.latitude is None or observation.longitude is None:
                continue
            if _distance_km(latitude, longitude, observation.latitude, observation.longitude) > float(
                settings.savings_baseline_radius_km
            ):
                continue
        candidates.append(
            (observation, source_unit, _converted_price(observation, source_unit, requested_unit))
        )
    return candidates


def create_baseline_snapshot(
    db: Session,
    *,
    product: Product,
    grade: ProductGrade,
    requested_unit: Unit,
    area: str,
    quantity: Decimal,
    created_by: str,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
) -> BaselineSnapshot:
    candidates = comparison_candidates(
        db,
        product_id=product.id,
        grade_id=grade.id,
        requested_unit=requested_unit,
        area=area,
        latitude=latitude,
        longitude=longitude,
        max_age_days=settings.savings_baseline_max_age_days,
    )
    source_count = len({item[0].source_name.casefold() for item in candidates})
    reason = None
    if len(candidates) < settings.savings_baseline_min_samples:
        reason = "INSUFFICIENT_COMPARABLE_OBSERVATIONS"
    elif source_count < settings.savings_baseline_min_sources:
        reason = "INSUFFICIENT_INDEPENDENT_SOURCES"

    baseline_unit_price = None
    baseline_total = None
    if reason is None:
        prices = sorted(price for _, _, price in candidates)
        middle = len(prices) // 2
        if len(prices) % 2:
            baseline_unit_price = prices[middle]
        else:
            baseline_unit_price = int(
                (Decimal(prices[middle - 1] + prices[middle]) / 2).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        baseline_total = int(
            (Decimal(baseline_unit_price) * quantity).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    observed_times = [aware_datetime(observation.observed_at) for observation, _, _ in candidates]
    return BaselineSnapshot(
        product_id=product.id,
        grade_id=grade.id,
        requested_unit_id=requested_unit.id,
        area=area.strip(),
        quantity=quantity,
        status="ELIGIBLE" if reason is None else "WITHHELD",
        reason=reason,
        method="median_of_comparable_observations",
        observation_ids=[observation.id for observation, _, _ in candidates],
        sample_size=len(candidates),
        source_count=source_count,
        baseline_unit_price_kobo=baseline_unit_price,
        baseline_total_kobo=baseline_total,
        oldest_observed_at=min(observed_times) if observed_times else None,
        newest_observed_at=max(observed_times) if observed_times else None,
        created_by=created_by,
    )

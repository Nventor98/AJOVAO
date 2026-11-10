from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.auth import create_access_token


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_engine):
    def get_test_db():
        with Session(db_engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _token(db_engine, user_id: str) -> str:
    with Session(db_engine) as db:
        user = db.get(User, user_id)
        assert user is not None
        return create_access_token(user)


def _headers(db_engine, user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(db_engine, user_id)}"}


def _create_user(db_engine, roles: list[str] | None = None) -> User:
    with Session(db_engine) as db:
        user = User(
            id=str(uuid4()),
            phone=f"+2348{uuid4().int % 10**10:010d}",
            phone_verified_at=datetime.now(timezone.utc),
            roles=roles or ["user"],
            permissions=["read:own", "write:own"],
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _catalogue(client: TestClient, headers: dict[str, str]) -> tuple[str, str, str]:
    category_response = client.post(
        "/api/v1/product-categories",
        headers=headers,
        json={"name": "Staples", "slug": "staples"},
    )
    assert category_response.status_code == 201
    category_id = category_response.json()["data"]["id"]

    unit_response = client.post(
        "/api/v1/units",
        headers=headers,
        json={"code": "kg", "name": "kilogram", "dimension": "mass", "to_base_factor": "1"},
    )
    assert unit_response.status_code == 201
    unit_id = unit_response.json()["data"]["id"]

    product_response = client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "category_id": category_id,
            "name": "Local rice",
            "slug": "local-rice",
            "base_unit_id": unit_id,
            "grades": [
                {"code": "A", "name": "Grade A"},
                {"code": "B", "name": "Grade B"},
            ],
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()["data"]
    return product["id"], product["grades"][0]["id"], unit_id


def test_catalogue_supplier_inventory_and_scorecard(client, db_engine) -> None:
    staff_user = _create_user(db_engine, roles=["admin"])
    supplier_user = _create_user(db_engine)
    staff_headers = _headers(db_engine, staff_user.id)
    supplier_headers = _headers(db_engine, supplier_user.id)
    product_id, grade_id, unit_id = _catalogue(client, staff_headers)

    supplier_response = client.post(
        "/api/v1/suppliers",
        headers=supplier_headers,
        json={
            "business_name": "Reliable Foods",
            "area": "Ikeja",
            "latitude": "6.60",
            "longitude": "3.35",
        },
    )
    assert supplier_response.status_code == 201
    supplier_id = supplier_response.json()["data"]["id"]
    assert supplier_response.json()["data"]["is_verified"] is False
    assert client.get("/api/v1/suppliers").json()["data"] == []

    verified = client.post(
        f"/api/v1/suppliers/{supplier_id}/verify",
        headers=staff_headers,
        json={"status": "VERIFIED"},
    )
    assert verified.status_code == 200

    stock = client.post(
        f"/api/v1/suppliers/{supplier_id}/inventory",
        headers=supplier_headers,
        json={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": unit_id,
            "quantity_delta": "5.5",
            "unit_price_kobo": 145000,
            "reason": "opening stock",
        },
    )
    assert stock.status_code == 201
    assert stock.json()["data"]["quantity"] == "5.500000"

    oversell = client.post(
        f"/api/v1/suppliers/{supplier_id}/inventory",
        headers=supplier_headers,
        json={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": unit_id,
            "quantity_delta": "-6",
            "unit_price_kobo": 145000,
            "reason": "invalid stock removal",
        },
    )
    assert oversell.status_code == 422
    stock_rows = client.get(
        f"/api/v1/suppliers/{supplier_id}/inventory",
        headers=supplier_headers,
    )
    assert stock_rows.json()["data"][0]["quantity"] == "5.500000"

    scorecard_update = client.put(
        f"/api/v1/suppliers/{supplier_id}/scorecard/data",
        headers=staff_headers,
        json={
            "deliveries_total": 10,
            "deliveries_successful": 9,
            "grade_checks_total": 8,
            "grade_checks_accurate": 7,
            "disputes_total": 1,
            "deliveries_on_time": 8,
        },
    )
    assert scorecard_update.status_code == 200
    hidden_scorecard = client.get(f"/api/v1/suppliers/{supplier_id}/scorecard")
    assert hidden_scorecard.status_code == 404

    consent = client.post(
        f"/api/v1/suppliers/{supplier_id}/scorecard-consent",
        headers=supplier_headers,
        params={"accept": "true"},
    )
    assert consent.status_code == 200
    scorecard = client.get(f"/api/v1/suppliers/{supplier_id}/scorecard")
    assert scorecard.status_code == 200
    assert scorecard.json()["data"]["delivery_success_rate"] == 0.9
    assert scorecard.json()["data"]["grade_accuracy_rate"] == 0.875


def test_price_comparison_snapshot_and_reviewed_index(client, db_engine) -> None:
    staff_user = _create_user(db_engine, roles=["admin"])
    headers = _headers(db_engine, staff_user.id)
    product_id, grade_id, unit_id = _catalogue(client, headers)
    now = datetime.now(timezone.utc)
    observation_ids: list[str] = []
    prices = [1000, 2000, 3000, 4000, 5000]
    for index, price in enumerate(prices):
        response = client.post(
            "/api/v1/price-observations",
            headers=headers,
            json={
                "product_id": product_id,
                "grade_id": grade_id,
                "unit_id": unit_id,
                "unit_price_kobo": price,
                "source_type": "market",
                "source_name": f"market-{index % 3}",
                "area": "Ikeja",
                "observed_at": (now - timedelta(hours=index + 1)).isoformat(),
            },
        )
        assert response.status_code == 201
        observation_ids.append(response.json()["data"]["id"])

    farm_gate = client.post(
        "/api/v1/price-observations",
        headers=headers,
        json={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": unit_id,
            "unit_price_kobo": 1,
            "source_type": "farm_gate",
            "source_name": "Farm gate",
            "area": "Ikeja",
            "observed_at": now.isoformat(),
        },
    )
    assert farm_gate.status_code == 201

    comparison = client.get(
        "/api/v1/prices/compare",
        params={"product_id": product_id, "grade_id": grade_id, "unit_id": unit_id, "area": "Ikeja"},
    )
    assert comparison.status_code == 200
    assert comparison.json()["data"]["sample_size"] == 5
    assert comparison.json()["data"]["source_count"] == 3
    assert comparison.json()["data"]["unit_price_kobo"] == 3000
    assert set(comparison.json()["data"]["observation_ids"]) == set(observation_ids)

    snapshot_response = client.post(
        "/api/v1/prices/baseline-snapshots",
        headers=headers,
        json={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": unit_id,
            "area": "Ikeja",
            "quantity": "2",
        },
    )
    assert snapshot_response.status_code == 201
    snapshot = snapshot_response.json()["data"]
    assert snapshot["status"] == "ELIGIBLE"
    assert snapshot["baseline_unit_price_kobo"] == 3000
    assert snapshot["baseline_total_kobo"] == 6000
    assert set(snapshot["observation_ids"]) == set(observation_ids)

    withheld = client.post(
        "/api/v1/prices/baseline-snapshots",
        headers=headers,
        json={
            "product_id": product_id,
            "grade_id": client.get(f"/api/v1/products/{product_id}").json()["data"]["grades"][1]["id"],
            "unit_id": unit_id,
            "area": "Ikeja",
            "quantity": "1",
        },
    )
    assert withheld.status_code == 201
    assert withheld.json()["data"]["status"] == "WITHHELD"
    assert withheld.json()["data"]["baseline_total_kobo"] is None
    assert withheld.json()["data"]["reason"] == "INSUFFICIENT_COMPARABLE_OBSERVATIONS"

    period = {
        "product_id": product_id,
        "grade_id": grade_id,
        "unit_id": unit_id,
        "area": "Ikeja",
        "period_start": (now - timedelta(days=1)).isoformat(),
        "period_end": (now - timedelta(minutes=1)).isoformat(),
    }
    published = client.post("/api/v1/price-index/publish", headers=headers, json=period)
    assert published.status_code == 201, published.json()
    assert published.json()["data"]["median_unit_price_kobo"] == 3000
    index = client.get("/api/v1/price-index", params={"product_id": product_id, "area": "Ikeja"})
    assert index.status_code == 200
    assert len(index.json()["data"]) == 1
    assert index.json()["data"][0]["sample_size"] == 5


def test_price_comparison_rejects_grade_and_unit_mismatch(client, db_engine) -> None:
    staff_user = _create_user(db_engine, roles=["admin"])
    headers = _headers(db_engine, staff_user.id)
    product_id, grade_id, unit_id = _catalogue(client, headers)
    category_id = client.get("/api/v1/product-categories").json()["data"][0]["id"]
    second_product = client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "category_id": category_id,
            "name": "Imported rice",
            "slug": "imported-rice",
            "base_unit_id": unit_id,
            "grades": [{"code": "X", "name": "Grade X"}],
        },
    )
    different_grade = second_product.json()["data"]["grades"][0]["id"]
    mismatched_grade = client.get(
        "/api/v1/prices/compare",
        params={
            "product_id": product_id,
            "grade_id": different_grade,
            "unit_id": unit_id,
            "area": "Ikeja",
        },
    )
    assert mismatched_grade.status_code == 422

    incompatible_unit = client.post(
        "/api/v1/units",
        headers=headers,
        json={"code": "l", "name": "litre", "dimension": "volume", "to_base_factor": "1"},
    ).json()["data"]["id"]
    mismatched_unit = client.get(
        "/api/v1/prices/compare",
        params={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": incompatible_unit,
            "area": "Ikeja",
        },
    )
    assert mismatched_unit.status_code == 422

    now = datetime.now(timezone.utc)
    unpublished = client.post(
        "/api/v1/price-index/publish",
        headers=headers,
        json={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": unit_id,
            "area": "Ikeja",
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": (now - timedelta(minutes=1)).isoformat(),
        },
    )
    assert unpublished.status_code == 422


def test_price_comparison_converts_compatible_units(client, db_engine) -> None:
    staff_user = _create_user(db_engine, roles=["admin"])
    headers = _headers(db_engine, staff_user.id)
    product_id, grade_id, kilogram_id = _catalogue(client, headers)
    gram_id = client.post(
        "/api/v1/units",
        headers=headers,
        json={"code": "g", "name": "gram", "dimension": "mass", "to_base_factor": "0.001"},
    ).json()["data"]["id"]
    now = datetime.now(timezone.utc)

    for unit_id, price, source in (
        (kilogram_id, 10_000, "wholesaler-kg"),
        (gram_id, 12, "market-g"),
    ):
        response = client.post(
            "/api/v1/price-observations",
            headers=headers,
            json={
                "product_id": product_id,
                "grade_id": grade_id,
                "unit_id": unit_id,
                "unit_price_kobo": price,
                "source_type": "market",
                "source_name": source,
                "area": "Ikeja",
                "observed_at": now.isoformat(),
            },
        )
        assert response.status_code == 201

    comparison = client.get(
        "/api/v1/prices/compare",
        params={
            "product_id": product_id,
            "grade_id": grade_id,
            "unit_id": kilogram_id,
            "area": "Ikeja",
        },
    )
    assert comparison.status_code == 200
    prices = {
        item["source_name"]: item["comparable_unit_price_kobo"]
        for item in comparison.json()["data"]["prices"]
    }
    assert prices == {"wholesaler-kg": 10_000, "market-g": 12_000}

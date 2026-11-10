from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.identity import CommunityAgent
from app.models.outbox import OutboxEvent
from app.models.purchasing import (
    PurchaseGroup,
    PurchaseOrder,
    PurchaseRequest,
    StandingBasketCycle,
)
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


def _headers(db_engine, user_id: str) -> dict[str, str]:
    with Session(db_engine) as db:
        user = db.get(User, user_id)
        assert user is not None
        token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _catalogue(client: TestClient, headers: dict[str, str]) -> tuple[str, str, str]:
    category = client.post(
        "/api/v1/product-categories",
        headers=headers,
        json={"name": "Staples", "slug": f"staples-{uuid4().hex[:8]}"},
    ).json()["data"]
    unit = client.post(
        "/api/v1/units",
        headers=headers,
        json={"code": f"kg-{uuid4().hex[:6]}", "name": f"Kilogram {uuid4().hex[:6]}", "dimension": "mass", "to_base_factor": "1"},
    ).json()["data"]
    product = client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "category_id": category["id"],
            "name": f"Rice {uuid4().hex[:6]}",
            "slug": f"rice-{uuid4().hex[:10]}",
            "base_unit_id": unit["id"],
            "grades": [{"code": "A", "name": "Grade A"}],
        },
    ).json()["data"]
    return product["id"], product["grades"][0]["id"], unit["id"]


def _community(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/communities",
        headers=headers,
        json={"name": f"Test community {uuid4().hex[:6]}", "community_type": "cooperative", "area": "Ikeja"},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _group_payload(community_id: str, product_id: str, grade_id: str, unit_id: str, **overrides) -> dict:
    payload = {
        "community_id": community_id,
        "name": "Rice purchase",
        "area": "Ikeja",
        "cutoff_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "delivery_method": "doorstep",
        "targets": [{"product_id": product_id, "grade_id": grade_id, "unit_id": unit_id}],
    }
    payload.update(overrides)
    return payload


def test_group_requests_aggregate_and_respect_cutoff(client, db_engine) -> None:
    admin = _create_user(db_engine, ["admin"])
    member = _create_user(db_engine)
    admin_headers = _headers(db_engine, admin.id)
    member_headers = _headers(db_engine, member.id)
    community_id = _community(client, admin_headers)
    assert client.post(f"/api/v1/communities/{community_id}/join", headers=member_headers).status_code == 201
    product_id, grade_id, unit_id = _catalogue(client, admin_headers)

    created = client.post(
        "/api/v1/purchase-groups",
        headers=admin_headers,
        json=_group_payload(community_id, product_id, grade_id, unit_id),
    )
    assert created.status_code == 201
    group = created.json()["data"]
    target_id = group["targets"][0]["id"]
    assert client.post(f"/api/v1/purchase-groups/{group['id']}/join", headers=admin_headers).status_code == 201
    assert client.post(f"/api/v1/purchase-groups/{group['id']}/join", headers=member_headers).status_code == 201
    for headers, quantity in ((admin_headers, "2"), (member_headers, "3")):
        request = client.post(
            f"/api/v1/purchase-groups/{group['id']}/requests",
            headers=headers,
            json={"target_id": target_id, "quantity": quantity},
        )
        assert request.status_code == 201

    summary = client.get(f"/api/v1/purchase-groups/{group['id']}/summary", headers=member_headers)
    assert summary.status_code == 200
    assert summary.json()["data"]["household_count"] == 2
    assert Decimal(summary.json()["data"]["items"][0]["quantity"]) == Decimal("5")
    assert "member_id" not in str(summary.json()["data"])

    with Session(db_engine) as db:
        stored_group = db.get(PurchaseGroup, group["id"])
        assert stored_group is not None
        stored_group.cutoff_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    closed = client.post("/api/v1/purchase-groups/process-due", headers=admin_headers)
    assert closed.status_code == 200
    assert closed.json()["data"]["closed_group_ids"] == [group["id"]]
    rejected = client.post(
        f"/api/v1/purchase-groups/{group['id']}/requests",
        headers=admin_headers,
        json={"target_id": target_id, "quantity": "1"},
    )
    assert rejected.status_code == 409
    cancelled = client.post(f"/api/v1/purchase-groups/{group['id']}/cancel", headers=admin_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "CANCELLED"


def test_confirming_quote_creates_idempotent_orders_and_baselines(client, db_engine) -> None:
    admin = _create_user(db_engine, ["admin"])
    member = _create_user(db_engine)
    supplier_user = _create_user(db_engine, ["supplier"])
    admin_headers = _headers(db_engine, admin.id)
    member_headers = _headers(db_engine, member.id)
    supplier_headers = _headers(db_engine, supplier_user.id)
    community_id = _community(client, admin_headers)
    assert client.post(f"/api/v1/communities/{community_id}/join", headers=member_headers).status_code == 201
    product_id, grade_id, unit_id = _catalogue(client, admin_headers)

    supplier = client.post(
        "/api/v1/suppliers",
        headers=supplier_headers,
        json={"business_name": "Test Foods", "area": "Ikeja"},
    )
    assert supplier.status_code == 201
    supplier_id = supplier.json()["data"]["id"]
    verified = client.post(
        f"/api/v1/suppliers/{supplier_id}/verify",
        headers=admin_headers,
        json={"status": "VERIFIED"},
    )
    assert verified.status_code == 200

    created = client.post(
        "/api/v1/purchase-groups",
        headers=admin_headers,
        json=_group_payload(community_id, product_id, grade_id, unit_id, minimum_households=2),
    )
    assert created.status_code == 201
    group_id = created.json()["data"]["id"]
    target_id = created.json()["data"]["targets"][0]["id"]
    for headers in (admin_headers, member_headers):
        assert client.post(f"/api/v1/purchase-groups/{group_id}/join", headers=headers).status_code == 201
    admin_request = client.post(
        f"/api/v1/purchase-groups/{group_id}/requests",
        headers=admin_headers,
        json={"target_id": target_id, "quantity": "0.5"},
    )
    member_request = client.post(
        f"/api/v1/purchase-groups/{group_id}/requests",
        headers=member_headers,
        json={"target_id": target_id, "quantity": "0.5"},
    )
    assert admin_request.status_code == member_request.status_code == 201

    with Session(db_engine) as db:
        stored_group = db.get(PurchaseGroup, group_id)
        assert stored_group is not None
        stored_group.cutoff_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.post(f"/api/v1/purchase-groups/{group_id}/close", headers=admin_headers).status_code == 200
    quote = client.post(
        f"/api/v1/purchase-groups/{group_id}/quotations",
        headers=supplier_headers,
        json={
            "delivery_fee_kobo": 101,
            "items": [{"target_id": target_id, "offered_quantity": "0.9", "unit_price_kobo": 1}],
        },
    )
    assert quote.status_code == 422
    quote = client.post(
        f"/api/v1/purchase-groups/{group_id}/quotations",
        headers=supplier_headers,
        json={
            "delivery_fee_kobo": 101,
            "items": [{"target_id": target_id, "offered_quantity": "1", "unit_price_kobo": 1}],
        },
    )
    assert quote.status_code == 201
    quote_id = quote.json()["data"]["id"]
    assert quote.json()["data"]["total_delivered_kobo"] == 103

    confirmed = client.post(
        f"/api/v1/purchase-groups/{group_id}/confirm",
        headers=admin_headers,
        json={"quotation_id": quote_id},
    )
    assert confirmed.status_code == 200
    data = confirmed.json()["data"]
    assert data["order_count"] == 2
    assert sum(order["total_amount_kobo"] for order in data["orders"]) == 103
    assert all(item["baseline_snapshot_id"] for order in data["orders"] for item in order["items"])
    duplicate = client.post(
        f"/api/v1/purchase-groups/{group_id}/confirm",
        headers=admin_headers,
        json={"quotation_id": quote_id},
    )
    assert duplicate.status_code == 200
    assert {order["id"] for order in duplicate.json()["data"]["orders"]} == {
        order["id"] for order in data["orders"]
    }
    assert client.get("/api/v1/orders", headers=member_headers).json()["meta"]["total"] == 1
    other_user = _create_user(db_engine)
    assert client.get(
        f"/api/v1/orders/{data['orders'][0]['id']}",
        headers=_headers(db_engine, other_user.id),
    ).status_code == 404
    with Session(db_engine) as db:
        assert len(db.scalars(select(PurchaseOrder).where(PurchaseOrder.group_id == group_id)).all()) == 2
        assert len(db.scalars(select(PurchaseRequest).where(PurchaseRequest.group_id == group_id)).all()) == 2
        first_order = db.scalar(
            select(PurchaseOrder).where(PurchaseOrder.group_id == group_id).order_by(PurchaseOrder.id)
        )
        assert first_order is not None
        first_order_id = first_order.id
        first_order.status = "PAID"
        db.commit()
    processing = client.post(
        f"/api/v1/orders/{first_order_id}/status",
        headers=supplier_headers,
        json={"status": "PROCESSING"},
    )
    assert processing.status_code == 200
    assert processing.json()["data"]["status"] == "PROCESSING"
    in_transit = client.post(
        f"/api/v1/orders/{first_order_id}/status",
        headers=admin_headers,
        json={"status": "IN_TRANSIT"},
    )
    assert in_transit.status_code == 200
    delivered = client.post(
        f"/api/v1/orders/{first_order_id}/status",
        headers=admin_headers,
        json={"status": "DELIVERED"},
    )
    assert delivered.status_code == 200


def test_agent_request_requires_active_member_consent(client, db_engine) -> None:
    admin = _create_user(db_engine, ["admin"])
    member = _create_user(db_engine)
    agent_user = _create_user(db_engine)
    admin_headers = _headers(db_engine, admin.id)
    member_headers = _headers(db_engine, member.id)
    agent_headers = _headers(db_engine, agent_user.id)
    community_id = _community(client, admin_headers)
    assert client.post(f"/api/v1/communities/{community_id}/join", headers=member_headers).status_code == 201
    assert client.post("/api/v1/agents/applications", headers=agent_headers).status_code == 201
    with Session(db_engine) as db:
        agent = db.scalar(select(CommunityAgent).where(CommunityAgent.user_id == agent_user.id))
        assert agent is not None
        agent_id = agent.id
    assert client.post(
        f"/api/v1/agents/{agent_id}/approve",
        headers=admin_headers,
        json={"identity_verified": True},
    ).status_code == 200
    assert client.post(
        f"/api/v1/communities/{community_id}/agents",
        headers=admin_headers,
        json={"agent_id": agent_user.id},
    ).status_code == 201

    consent_response = client.post(
        f"/api/v1/members/{member.id}/agent-consents",
        headers=member_headers,
        json={
            "agent_id": agent_user.id,
            "scopes": ["orders:place"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert consent_response.status_code == 201
    consent_id = consent_response.json()["data"]["id"]
    product_id, grade_id, unit_id = _catalogue(client, admin_headers)
    group = client.post(
        "/api/v1/purchase-groups",
        headers=admin_headers,
        json=_group_payload(community_id, product_id, grade_id, unit_id),
    ).json()["data"]
    target_id = group["targets"][0]["id"]
    assert client.post(f"/api/v1/purchase-groups/{group['id']}/join", headers=member_headers).status_code == 201
    denied = client.post(
        f"/api/v1/purchase-groups/{group['id']}/requests",
        headers=agent_headers,
        json={"member_id": member.id, "target_id": target_id, "quantity": "1"},
    )
    assert denied.status_code == 403
    accepted = client.post(
        f"/api/v1/purchase-groups/{group['id']}/requests",
        headers=agent_headers,
        json={
            "member_id": member.id,
            "consent_id": consent_id,
            "target_id": target_id,
            "quantity": "1",
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["data"]["placed_by_agent_id"] == agent_user.id
    assert accepted.json()["data"]["consent_id"] == consent_id


def test_request_update_and_withdrawal_are_owner_scoped_and_before_cutoff(client, db_engine) -> None:
    admin = _create_user(db_engine, ["admin"])
    member = _create_user(db_engine)
    admin_headers = _headers(db_engine, admin.id)
    member_headers = _headers(db_engine, member.id)
    community_id = _community(client, admin_headers)
    assert client.post(f"/api/v1/communities/{community_id}/join", headers=member_headers).status_code == 201
    product_id, grade_id, unit_id = _catalogue(client, admin_headers)
    group = client.post(
        "/api/v1/purchase-groups",
        headers=admin_headers,
        json=_group_payload(community_id, product_id, grade_id, unit_id),
    ).json()["data"]
    target_id = group["targets"][0]["id"]
    for headers in (admin_headers, member_headers):
        assert client.post(f"/api/v1/purchase-groups/{group['id']}/join", headers=headers).status_code == 201
    admin_request = client.post(
        f"/api/v1/purchase-groups/{group['id']}/requests",
        headers=admin_headers,
        json={"target_id": target_id, "quantity": "1"},
    ).json()["data"]
    member_request = client.post(
        f"/api/v1/purchase-groups/{group['id']}/requests",
        headers=member_headers,
        json={"target_id": target_id, "quantity": "2"},
    ).json()["data"]
    updated = client.patch(
        f"/api/v1/purchase-requests/{member_request['id']}",
        headers=member_headers,
        json={"quantity": "3"},
    )
    assert updated.status_code == 200
    forbidden = client.delete(
        f"/api/v1/purchase-requests/{admin_request['id']}",
        headers=member_headers,
    )
    assert forbidden.status_code == 403
    withdrawn = client.delete(
        f"/api/v1/purchase-requests/{admin_request['id']}",
        headers=admin_headers,
    )
    assert withdrawn.status_code == 200
    summary = client.get(f"/api/v1/purchase-groups/{group['id']}/summary", headers=member_headers).json()["data"]
    assert summary["household_count"] == 1
    assert Decimal(summary["items"][0]["quantity"]) == Decimal("3")
    with Session(db_engine) as db:
        stored_group = db.get(PurchaseGroup, group["id"])
        assert stored_group is not None
        stored_group.cutoff_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    late_update = client.patch(
        f"/api/v1/purchase-requests/{member_request['id']}",
        headers=member_headers,
        json={"quantity": "4"},
    )
    assert late_update.status_code == 409


def test_standing_basket_cycle_is_idempotent_and_can_be_skipped(client, db_engine) -> None:
    admin = _create_user(db_engine, ["admin"])
    member = _create_user(db_engine)
    admin_headers = _headers(db_engine, admin.id)
    member_headers = _headers(db_engine, member.id)
    community_id = _community(client, admin_headers)
    assert client.post(f"/api/v1/communities/{community_id}/join", headers=member_headers).status_code == 201
    product_id, grade_id, unit_id = _catalogue(client, admin_headers)
    response = client.post(
        "/api/v1/baskets",
        headers=admin_headers,
        json={
            "community_id": community_id,
            "name": "Monthly staples",
            "area": "Ikeja",
            "cadence": "monthly",
            "cutoff_after_days": 2,
            "next_cycle_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            "delivery_method": "doorstep",
            "targets": [{"product_id": product_id, "grade_id": grade_id, "unit_id": unit_id, "quantity": "2"}],
        },
    )
    assert response.status_code == 201
    basket_id = response.json()["data"]["id"]
    assert client.post(f"/api/v1/baskets/{basket_id}/subscribe", headers=member_headers).status_code == 200
    opened = client.post("/api/v1/baskets/process-due-cycles", headers=admin_headers)
    assert opened.status_code == 200
    assert opened.json()["data"]["count"] == 1
    repeated = client.post("/api/v1/baskets/process-due-cycles", headers=admin_headers)
    assert repeated.json()["data"]["count"] == 0
    cycles = client.get(f"/api/v1/baskets/{basket_id}/cycles", headers=member_headers)
    assert cycles.status_code == 200
    assert cycles.json()["meta"]["total"] == 1
    cycle_id = cycles.json()["data"][0]["id"]
    joined = client.post(
        f"/api/v1/baskets/{basket_id}/cycles/{cycle_id}/join",
        headers=member_headers,
    )
    assert joined.status_code == 200
    group_id = opened.json()["data"]["opened_cycles"][0]["group_id"]
    with Session(db_engine) as db:
        group = db.get(PurchaseGroup, group_id)
        assert group is not None
        request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.group_id == group_id))
        assert request is not None and request.quantity == 2
    skipped = client.post(
        f"/api/v1/baskets/{basket_id}/cycles/{cycle_id}/skip",
        headers=member_headers,
    )
    assert skipped.status_code == 200
    with Session(db_engine) as db:
        request = db.scalar(select(PurchaseRequest).where(PurchaseRequest.group_id == group_id))
        assert request is not None and request.status == "WITHDRAWN"


def test_demand_signal_is_anonymised_and_threshold_gated(client, db_engine, monkeypatch) -> None:
    monkeypatch.setattr(settings, "demand_signal_min_households", 2)
    admin = _create_user(db_engine, ["admin"])
    member = _create_user(db_engine)
    admin_headers = _headers(db_engine, admin.id)
    member_headers = _headers(db_engine, member.id)
    community_id = _community(client, admin_headers)
    assert client.post(f"/api/v1/communities/{community_id}/join", headers=member_headers).status_code == 201
    product_id, grade_id, unit_id = _catalogue(client, admin_headers)
    group = client.post(
        "/api/v1/purchase-groups",
        headers=admin_headers,
        json=_group_payload(community_id, product_id, grade_id, unit_id),
    ).json()["data"]
    target_id = group["targets"][0]["id"]
    for headers in (admin_headers, member_headers):
        assert client.post(f"/api/v1/purchase-groups/{group['id']}/join", headers=headers).status_code == 201
        assert client.post(
            f"/api/v1/purchase-groups/{group['id']}/requests",
            headers=headers,
            json={"target_id": target_id, "quantity": "1"},
        ).status_code == 201
    with Session(db_engine) as db:
        stored_group = db.get(PurchaseGroup, group["id"])
        assert stored_group is not None
        stored_group.cutoff_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.post(f"/api/v1/purchase-groups/{group['id']}/close", headers=admin_headers).status_code == 200
    with Session(db_engine) as db:
        event = db.scalar(
            select(OutboxEvent).where(OutboxEvent.event_name == "purchase_group.demand_published")
        )
        assert event is not None
        assert event.payload["household_count"] == 2
        serialized = str(event.payload)
        assert admin.id not in serialized
        assert member.id not in serialized

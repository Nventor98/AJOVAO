from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.auth import create_access_token, send_verification_code
from app.services.identity import ensure_agent_consent
from app.api.auth import get_verification_sender
from app.shared.rate_limit import get_rate_limiter
from app.db.types import point_wkt
from app.models.identity import Address


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
    sender_codes: dict[str, str] = {}

    def sender(phone: str, code: str) -> None:
        sender_codes[phone] = code

    def get_test_db():
        with Session(db_engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_verification_sender] = lambda: sender
    app.dependency_overrides[get_rate_limiter] = lambda: _AllowAllRateLimiter()
    app.state.test_sender_codes = sender_codes
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.test_sender_codes


class _AllowAllRateLimiter:
    def allow(self, key: str, *, requests_per_minute: int | None = None) -> tuple[bool, int]:
        return True, 0


def create_user(db_engine, *, roles: list[str] | None = None) -> User:
    with Session(db_engine) as db:
        user = User(
            phone=f"+234800{datetime.now().microsecond:06d}",
            full_name="Test User",
            password_hash="not-used",
            phone_verified_at=datetime.now(timezone.utc),
            roles=roles or ["user"],
            permissions=["read:own", "write:own"],
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def token_for(db_engine, user_id: str) -> str:
    with Session(db_engine) as db:
        user = db.get(User, user_id)
        assert user is not None
        return create_access_token(user)


def test_registration_verification_login_and_profile(client) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "phone": "+234 801-234-5678",
            "password": "a-very-long-test-password",
            "full_name": "A Test User",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["phone_verification_required"] is True
    code = client.app.state.test_sender_codes["+2348012345678"]

    verified = client.post(
        "/api/v1/auth/verify-phone",
        json={"phone": "+2348012345678", "code": code},
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["verified"] is True

    login = client.post(
        "/api/v1/auth/login",
        json={"phone": "+2348012345678", "password": "a-very-long-test-password"},
    )
    assert login.status_code == 200
    access_token = login.json()["data"]["access_token"]
    profile = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert profile.status_code == 200
    assert profile.json()["data"]["phone_verified"] is True

    updated = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"preferred_language": "yo"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["preferred_language"] == "yo"


def test_unauthenticated_profile_is_rejected(client) -> None:
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_rate_limit_is_applied_before_password_verification(client) -> None:
    class DenyLimiter:
        def allow(self, _key: str, *, requests_per_minute: int | None = None) -> tuple[bool, int]:
            return False, 19

    client.app.dependency_overrides[get_rate_limiter] = lambda: DenyLimiter()
    response = client.post(
        "/api/v1/auth/login",
        json={"phone": "+2348012345678", "password": "not-a-real-password"},
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "19"


def test_twilio_sender_posts_sms_with_basic_auth(monkeypatch) -> None:
    from app.core.config import settings
    import app.services.auth as auth_service

    monkeypatch.setattr(settings, "twilio_account_sid", "AC123")
    monkeypatch.setattr(settings, "twilio_auth_token", "test-token")
    monkeypatch.setattr(settings, "twilio_from_number", "+15005550006")
    captured = {}

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["body"] = parse_qs(request.data.decode("ascii"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(auth_service, "urlopen", fake_urlopen)
    send_verification_code("+2348012345678", "123456")

    assert urlparse(captured["url"]).hostname == "api.twilio.com"
    assert captured["headers"]["Authorization"] == (
        "Basic " + base64.b64encode(b"AC123:test-token").decode("ascii")
    )
    assert captured["body"]["To"] == ["+2348012345678"]
    assert captured["body"]["From"] == ["+15005550006"]
    assert "123456" in captured["body"]["Body"][0]
    assert captured["timeout"] == 10


def test_twilio_sender_requires_configuration(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "twilio_account_sid", None)
    monkeypatch.setattr(settings, "twilio_auth_token", None)
    monkeypatch.setattr(settings, "twilio_from_number", None)
    with pytest.raises(HTTPException) as error:
        send_verification_code("+2348012345678", "123456")
    assert error.value.status_code == 503


def test_location_fields_compile_to_postgis_geometry() -> None:
    create_sql = str(CreateTable(Address.__table__).compile(dialect=postgresql.dialect()))
    insert_sql = str(
        insert(Address)
        .values(location=point_wkt(6.6, 3.35))
        .compile(dialect=postgresql.dialect())
    )
    assert "geometry(POINT,4326)" in create_sql
    assert "ST_GeomFromEWKT" in insert_sql


def test_community_membership_and_address_ownership(client, db_engine) -> None:
    owner = create_user(db_engine)
    member = create_user(db_engine)
    owner_token = token_for(db_engine, owner.id)
    member_token = token_for(db_engine, member.id)

    community_response = client.post(
        "/api/v1/communities",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Community One", "community_type": "cooperative", "area": "Ikeja"},
    )
    assert community_response.status_code == 201
    community_id = community_response.json()["data"]["id"]

    headers = {"Authorization": f"Bearer {member_token}"}
    joined = client.post(f"/api/v1/communities/{community_id}/join", headers=headers)
    assert joined.status_code == 201
    duplicate = client.post(f"/api/v1/communities/{community_id}/join", headers=headers)
    assert duplicate.status_code == 409

    address = client.post(
        "/api/v1/addresses",
        headers=headers,
        json={
            "label": "Home",
            "address_line": "1 Test Street",
            "area": "Ikeja",
            "city": "Lagos",
            "state": "Lagos",
            "latitude": 6.6,
            "longitude": 3.35,
        },
    )
    assert address.status_code == 201
    address_id = address.json()["data"]["id"]

    unauthorized = client.patch(
        f"/api/v1/addresses/{address_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"label": "Taken over"},
    )
    assert unauthorized.status_code == 404

    point = client.post(
        f"/api/v1/communities/{community_id}/collection-points",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Main Hall", "address_line": "2 Test Road"},
    )
    assert point.status_code == 201
    points = client.get(f"/api/v1/communities/{community_id}/collection-points", headers=headers)
    assert points.status_code == 200
    assert len(points.json()["data"]) == 1


def test_agent_consent_requires_assignment_and_can_be_revoked(client, db_engine) -> None:
    admin = create_user(db_engine, roles=["admin"])
    member = create_user(db_engine)
    agent_user = create_user(db_engine)
    admin_headers = {"Authorization": f"Bearer {token_for(db_engine, admin.id)}"}
    member_headers = {"Authorization": f"Bearer {token_for(db_engine, member.id)}"}

    community_response = client.post(
        "/api/v1/communities",
        headers=admin_headers,
        json={"name": "Agent Community", "community_type": "estate"},
    )
    community_id = community_response.json()["data"]["id"]
    assert client.post(
        f"/api/v1/communities/{community_id}/join",
        headers=member_headers,
    ).status_code == 201

    application = client.post(
        "/api/v1/agents/applications",
        headers={"Authorization": f"Bearer {token_for(db_engine, agent_user.id)}"},
    )
    assert application.status_code == 201
    agent_record_id = application.json()["data"]["id"]

    approval = client.post(
        f"/api/v1/agents/{agent_record_id}/approve",
        headers=admin_headers,
        json={"identity_verified": True},
    )
    assert approval.status_code == 200
    assignment = client.post(
        f"/api/v1/communities/{community_id}/agents",
        headers=admin_headers,
        json={"agent_id": agent_user.id},
    )
    assert assignment.status_code == 201

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

    with Session(db_engine) as db:
        consent = ensure_agent_consent(
            db,
            agent_id=agent_user.id,
            member_id=member.id,
            scope="orders:place",
        )
        assert consent.id == consent_id

    with Session(db_engine) as db, pytest.raises(HTTPException, match="Valid member consent"):
        ensure_agent_consent(
            db,
            agent_id=agent_user.id,
            member_id=member.id,
            scope="orders:amend",
        )

    suspended = client.post(
        f"/api/v1/agents/{agent_record_id}/suspend",
        headers=admin_headers,
    )
    assert suspended.status_code == 200
    with Session(db_engine) as db, pytest.raises(HTTPException, match="Agent is not approved"):
        ensure_agent_consent(
            db,
            agent_id=agent_user.id,
            member_id=member.id,
            scope="orders:place",
        )
    revoked = client.delete(
        f"/api/v1/members/{member.id}/agent-consents/{consent_id}",
        headers=member_headers,
    )
    assert revoked.status_code == 200

    with Session(db_engine) as db, pytest.raises(HTTPException):
        ensure_agent_consent(
            db,
            agent_id=agent_user.id,
            member_id=member.id,
            scope="orders:place",
        )


def test_phone_verified_user_can_enable_farmer_role(client, db_engine) -> None:
    farmer = create_user(db_engine)
    headers = {"Authorization": f"Bearer {token_for(db_engine, farmer.id)}"}

    enabled = client.post("/api/v1/farmers/role", headers=headers)
    assert enabled.status_code == 200
    assert enabled.json()["data"]["role"] == "farmer"
    assert enabled.json()["data"]["already_enabled"] is False
    profile = client.get("/api/v1/users/me", headers=headers).json()["data"]
    assert profile["roles"] == ["user", "farmer"]
    with Session(db_engine) as db:
        stored_farmer = db.get(User, farmer.id)
        assert stored_farmer is not None
        assert {"read:farmers", "write:farmers"}.issubset(set(stored_farmer.permissions))

    repeated = client.post("/api/v1/farmers/role", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["already_enabled"] is True


def test_farmer_role_requires_phone_verification(client, db_engine) -> None:
    user = create_user(db_engine)
    with Session(db_engine) as db:
        stored_user = db.get(User, user.id)
        assert stored_user is not None
        stored_user.phone_verified_at = None
        db.commit()
    headers = {"Authorization": f"Bearer {token_for(db_engine, user.id)}"}

    response = client.post("/api/v1/farmers/role", headers=headers)
    assert response.status_code == 401
    with Session(db_engine) as db:
        stored_user = db.get(User, user.id)
        assert stored_user is not None
        assert "farmer" not in stored_user.roles


def test_agent_can_enable_farmer_role_only_with_scoped_active_consent(client, db_engine) -> None:
    admin = create_user(db_engine, roles=["admin"])
    member = create_user(db_engine)
    agent_user = create_user(db_engine)
    admin_headers = {"Authorization": f"Bearer {token_for(db_engine, admin.id)}"}
    member_headers = {"Authorization": f"Bearer {token_for(db_engine, member.id)}"}
    agent_headers = {"Authorization": f"Bearer {token_for(db_engine, agent_user.id)}"}

    community_response = client.post(
        "/api/v1/communities",
        headers=admin_headers,
        json={"name": "Farmer Community", "community_type": "cooperative"},
    )
    community_id = community_response.json()["data"]["id"]
    assert client.post(
        f"/api/v1/communities/{community_id}/join",
        headers=member_headers,
    ).status_code == 201

    application = client.post("/api/v1/agents/applications", headers=agent_headers)
    assert application.status_code == 201
    agent_record_id = application.json()["data"]["id"]
    assert client.post(
        f"/api/v1/agents/{agent_record_id}/approve",
        headers=admin_headers,
        json={"identity_verified": True},
    ).status_code == 200
    assert client.post(
        f"/api/v1/communities/{community_id}/agents",
        headers=admin_headers,
        json={"agent_id": agent_user.id},
    ).status_code == 201
    agent_headers = {"Authorization": f"Bearer {token_for(db_engine, agent_user.id)}"}

    order_consent = client.post(
        f"/api/v1/members/{member.id}/agent-consents",
        headers=member_headers,
        json={
            "agent_id": agent_user.id,
            "scopes": ["orders:place"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert order_consent.status_code == 201
    wrong_scope = client.post(
        f"/api/v1/members/{member.id}/farmer-role",
        headers=agent_headers,
        json={"consent_id": order_consent.json()["data"]["id"]},
    )
    assert wrong_scope.status_code == 403

    farmer_consent = client.post(
        f"/api/v1/members/{member.id}/agent-consents",
        headers=member_headers,
        json={
            "agent_id": agent_user.id,
            "scopes": ["farmer:register"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    )
    assert farmer_consent.status_code == 201
    consent_id = farmer_consent.json()["data"]["id"]
    assisted = client.post(
        f"/api/v1/members/{member.id}/farmer-role",
        headers=agent_headers,
        json={"consent_id": consent_id},
    )
    assert assisted.status_code == 200
    assert assisted.json()["data"]["role"] == "farmer"
    assert assisted.json()["data"]["consent_id"] == consent_id
    member_profile = client.get("/api/v1/users/me", headers=member_headers).json()["data"]
    assert "farmer" in member_profile["roles"]
    with Session(db_engine) as db:
        stored_member = db.get(User, member.id)
        assert stored_member is not None
        assert {"read:farmers", "write:farmers"}.issubset(set(stored_member.permissions))

    assert client.delete(
        f"/api/v1/members/{member.id}/agent-consents/{consent_id}",
        headers=member_headers,
    ).status_code == 200
    revoked_consent = client.post(
        f"/api/v1/members/{member.id}/farmer-role",
        headers=agent_headers,
        json={"consent_id": consent_id},
    )
    assert revoked_consent.status_code == 403
    with Session(db_engine) as db:
        stored_member = db.get(User, member.id)
        assert stored_member is not None
        assert "farmer" in stored_member.roles

def test_malformed_access_token_is_rejected(client) -> None:
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_access_token_is_rejected(client, db_engine) -> None:
    from app.core.config import settings

    user = create_user(db_engine)
    expired_token = jwt.encode(
        {
            "sub": user.id,
            "roles": user.roles,
            "permissions": user.permissions,
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"

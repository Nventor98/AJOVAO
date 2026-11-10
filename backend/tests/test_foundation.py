from redis.exceptions import ConnectionError as RedisConnectionError
from fastapi.testclient import TestClient

from app.main import app
from app.shared.permissions import Permission, Role, require_roles
from app.shared.rate_limit import get_redis_client
from app.shared.responses import ok

client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "NaijaLife AI" in payload["data"]["message"]


def test_health_endpoints() -> None:
    class RedisProbe:
        def ping(self) -> bool:
            return True

    app.dependency_overrides[get_redis_client] = lambda: RedisProbe()
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["success"] is True

        ready = client.get("/api/v1/ready")
    finally:
        app.dependency_overrides.pop(get_redis_client, None)
    assert ready.status_code == 200
    assert ready.json()["success"] is True
    assert ready.json()["data"]["database"] == "ready"
    assert ready.json()["data"]["redis"] == "ready"


def test_readiness_fails_when_redis_is_unavailable() -> None:
    class OfflineRedis:
        def ping(self) -> None:
            raise RedisConnectionError("offline")

    app.dependency_overrides[get_redis_client] = lambda: OfflineRedis()
    try:
        ready = client.get("/api/v1/ready")
    finally:
        app.dependency_overrides.pop(get_redis_client, None)
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_ok_helper() -> None:
    payload = ok({"status": "ok"}, meta={"page": 1})
    assert payload["success"] is True
    assert payload["meta"]["page"] == 1


def test_permission_helpers() -> None:
    class UserStub:
        roles = [Role.ADMIN.value]
        permissions = [Permission.READ_USERS.value]
        user_id = "user-123"

    require_roles(UserStub(), Role.ADMIN.value)
    assert True

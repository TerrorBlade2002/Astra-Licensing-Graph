"""Health, error-shape, and correlation-header API tests."""

from __future__ import annotations

import uuid

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.conftest import make_test_settings


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_readiness_with_database(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_readiness_returns_503_when_database_unavailable(
    test_database_url: str,
) -> None:
    # Point the app at a closed port on localhost.
    bad_url = "postgresql+asyncpg://astra:wrong@localhost:59999/nope"
    app = create_app(make_test_settings(bad_url))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            live = await client.get("/health/live")
            assert live.status_code == 200  # liveness never touches the DB
            ready = await client.get("/health/ready")
            assert ready.status_code == 503


async def test_correlation_header_is_echoed_when_valid(client: AsyncClient) -> None:
    value = str(uuid.uuid4())
    response = await client.get("/health/live", headers={"X-Correlation-ID": value})
    assert response.headers["X-Correlation-ID"] == value


async def test_invalid_correlation_header_is_replaced(client: AsyncClient) -> None:
    response = await client.get(
        "/health/live", headers={"X-Correlation-ID": "<script>alert(1)</script>"}
    )
    echoed = response.headers["X-Correlation-ID"]
    assert echoed != "<script>alert(1)</script>"
    uuid.UUID(echoed)  # must be a well-formed UUID


async def test_error_shape_for_missing_resource(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/mailboxes/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]


async def test_error_shape_for_validation_error(client: AsyncClient) -> None:
    response = await client.get("/api/v1/emails", params={"page": 0})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["errors"]


async def test_system_version(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/version")
    assert response.status_code == 200
    body = response.json()
    assert body["app_name"]
    assert body["environment"] == "test"
    assert body["migration_revision"] == "0005_controlled_communications"

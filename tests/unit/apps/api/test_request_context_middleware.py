"""Tests for request and correlation identifier middleware."""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.platform.config import Settings
from erp.platform.database import ManagedDatabase
from erp.platform.observability import get_correlation_id, get_request_id


class AvailableDatabase(ManagedDatabase):
    """Database double used by middleware tests."""

    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


def test_middleware_generates_request_and_correlation_ids() -> None:
    client = TestClient(create_app(Settings(), AvailableDatabase()))

    response = client.get("/health/live")

    request_id = response.headers["X-Request-ID"]
    correlation_id = response.headers["X-Correlation-ID"]
    assert str(UUID(request_id)) == request_id
    assert correlation_id == request_id
    assert get_request_id() is None
    assert get_correlation_id() is None


def test_middleware_preserves_valid_inbound_ids() -> None:
    client = TestClient(create_app(Settings(), AvailableDatabase()))
    request_id = str(uuid4())
    correlation_id = str(uuid4())

    response = client.get(
        "/health/live",
        headers={
            "X-Request-ID": request_id,
            "X-Correlation-ID": correlation_id,
        },
    )

    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["X-Correlation-ID"] == correlation_id


def test_middleware_replaces_invalid_inbound_ids() -> None:
    client = TestClient(create_app(Settings(), AvailableDatabase()))

    response = client.get(
        "/health/live",
        headers={"X-Request-ID": "invalid", "X-Correlation-ID": "also-invalid"},
    )

    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id
    assert response.headers["X-Correlation-ID"] == request_id

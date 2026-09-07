"""Contract tests for the health endpoints."""

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.platform.config import Settings
from erp.platform.database import DatabaseUnavailableError, ManagedDatabase


class AvailableDatabase(ManagedDatabase):
    """Test double for a reachable PostgreSQL instance."""

    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


class UnavailableDatabase(ManagedDatabase):
    """Test double for an unreachable PostgreSQL instance."""

    async def ping(self) -> None:
        raise DatabaseUnavailableError

    async def dispose(self) -> None:
        return None


def test_liveness_does_not_depend_on_postgresql() -> None:
    client = TestClient(create_app(Settings(), UnavailableDatabase()))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_available_postgresql() -> None:
    client = TestClient(create_app(Settings(), AvailableDatabase()))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgresql": "up"},
    }


def test_readiness_returns_service_unavailable_for_postgresql_failure() -> None:
    client = TestClient(create_app(Settings(), UnavailableDatabase()))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgresql": "down"},
    }

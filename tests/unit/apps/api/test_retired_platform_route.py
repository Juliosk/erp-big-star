"""Regression guard for removal of the disposable Sprint 1 endpoint."""

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.platform.config import Settings
from erp.platform.database import ManagedDatabase


class AvailableDatabase(ManagedDatabase):
    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


def test_disposable_platform_test_endpoint_is_no_longer_registered() -> None:
    application = create_app(
        Settings.model_validate({"environment": "test"}),
        AvailableDatabase(),
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "retired"},
            headers={"Idempotency-Key": "must-not-exist"},
        )

    assert response.status_code == 404

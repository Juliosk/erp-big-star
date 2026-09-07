"""HTTP boundary tests for the disposable platform endpoint controls."""

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.platform.config import Settings
from erp.platform.database import ManagedDatabase


class AvailableDatabase(ManagedDatabase):
    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


def test_platform_test_endpoint_is_disabled_by_default_in_production() -> None:
    application = create_app(
        Settings.model_validate({"environment": "production"}),
        AvailableDatabase(),
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "must stay closed"},
            headers={"Idempotency-Key": "production-test"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLATFORM_TEST_ENDPOINT_DISABLED"


def test_platform_test_endpoint_requires_idempotency_key() -> None:
    application = create_app(Settings.model_validate({"environment": "test"}))

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "missing key"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

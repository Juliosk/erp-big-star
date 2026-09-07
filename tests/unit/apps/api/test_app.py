"""Tests for the FastAPI application factory."""

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.platform.config import Settings


def test_create_app_exposes_openapi_metadata() -> None:
    settings = Settings.model_validate(
        {"app_name": "ERP Test", "app_version": "9.9.9", "environment": "test"}
    )
    application = create_app(settings)
    client = TestClient(application)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"] == {
        "title": "ERP Test",
        "version": "9.9.9",
    }
    assert application.state.settings is settings

"""Integration test for readiness against the local PostgreSQL service."""

import pytest
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.platform.config import get_settings


@pytest.mark.integration
def test_readiness_reaches_postgresql() -> None:
    with TestClient(create_app(get_settings())) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["postgresql"] == "up"

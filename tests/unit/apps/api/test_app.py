"""Tests for the FastAPI application factory."""

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app


def test_create_app_exposes_openapi_metadata() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"] == {
        "title": "ERP Big Star / Forma Kids",
        "version": "0.1.0",
    }

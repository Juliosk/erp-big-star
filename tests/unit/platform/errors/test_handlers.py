"""Contract tests for standardized HTTP errors."""

from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from erp.apps.api.app import create_app
from erp.platform.config import Settings
from erp.platform.database import ManagedDatabase
from erp.platform.errors import ApplicationError, ErrorDetail


class AvailableDatabase(ManagedDatabase):
    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


class InputBody(BaseModel):
    name: str = Field(min_length=3)


def build_client(*, raise_server_exceptions: bool = True) -> TestClient:
    application = create_app(
        Settings.model_validate({"environment": "test"}),
        AvailableDatabase(),
    )
    router = APIRouter()

    @router.get("/expected")
    async def expected() -> None:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The resource version is stale.",
            status_code=409,
            details=[ErrorDetail(message="Expected version 2.")],
        )

    @router.post("/validated")
    async def validated(body: InputBody) -> InputBody:
        return body

    @router.get("/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("internal secret")

    application.include_router(router)
    return TestClient(application, raise_server_exceptions=raise_server_exceptions)


def test_application_error_uses_stable_envelope_and_correlation_id() -> None:
    correlation_id = "4db122b5-ff79-432c-a31c-12a6bebbe5d0"

    with build_client() as client:
        response = client.get("/expected", headers={"X-Correlation-ID": correlation_id})

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "VERSION_CONFLICT",
            "message": "The resource version is stale.",
            "details": [{"location": [], "message": "Expected version 2.", "type": None}],
            "correlation_id": correlation_id,
        }
    }


def test_validation_error_uses_standard_contract() -> None:
    with build_client() as client:
        response = client.post("/validated", json={"name": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["location"] == ["body", "name"]


def test_unexpected_error_hides_internal_exception() -> None:
    with build_client(raise_server_exceptions=False) as client:
        response = client.get("/unexpected")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text

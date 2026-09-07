"""Process liveness and dependency readiness routes."""

import asyncio
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from erp.platform.config import Settings
from erp.platform.database import DatabaseHealthProbe, DatabaseUnavailableError

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    """Stable liveness contract."""

    status: Literal["alive"] = "alive"


class ReadinessChecks(BaseModel):
    """Status of dependencies required to serve traffic."""

    postgresql: Literal["up", "down"]


class ReadinessResponse(BaseModel):
    """Stable readiness contract."""

    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


def get_database_probe(request: Request) -> DatabaseHealthProbe:
    """Resolve the database probe owned by the application lifecycle."""
    return cast(DatabaseHealthProbe, request.app.state.database)


def get_application_settings(request: Request) -> Settings:
    """Resolve the typed settings attached by the application factory."""
    return cast(Settings, request.app.state.settings)


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Report that the API process can execute requests."""
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(
    database: Annotated[DatabaseHealthProbe, Depends(get_database_probe)],
    settings: Annotated[Settings, Depends(get_application_settings)],
) -> ReadinessResponse | JSONResponse:
    """Report whether PostgreSQL is reachable within the readiness budget."""
    try:
        async with asyncio.timeout(settings.readiness_database_timeout_seconds):
            await database.ping()
    except DatabaseUnavailableError, TimeoutError:
        payload = ReadinessResponse(
            status="not_ready",
            checks=ReadinessChecks(postgresql="down"),
        )
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))

    return ReadinessResponse(status="ready", checks=ReadinessChecks(postgresql="up"))


__all__ = ["router"]

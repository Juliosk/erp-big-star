"""Non-production endpoint proving the full Sprint 1 platform flow."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from erp.modules.platform_test.application import (
    CreateTestEntityCommand,
    CreateTestEntityResult,
    CreateTestEntityService,
    TestEntityDeliveryTimeoutError,
)
from erp.modules.platform_test.domain import TestEntityStatus
from erp.platform.config import Settings
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key
from erp.platform.messaging import BrokerPublishError, BrokerUnavailableError

router = APIRouter(prefix="/api/v1/platform", tags=["platform-validation"])


class CreateTestEntityRequest(BaseModel):
    """Minimal body for the disposable golden-flow command."""

    name: str = Field(min_length=1, max_length=200)


class CreateTestEntityResponse(BaseModel):
    """Observable evidence returned after create, publish and consume."""

    id: UUID
    name: str
    status: TestEntityStatus
    version: int
    event_id: UUID
    audit_event_ids: list[UUID]
    idempotency_replayed: bool


def get_test_entity_service(request: Request) -> CreateTestEntityService:
    """Resolve the workflow composed at the application's outer boundary."""
    service = getattr(request.app.state, "test_entity_service", None)
    if not isinstance(service, CreateTestEntityService):
        raise ApplicationError(
            code="PLATFORM_TEST_ENDPOINT_UNAVAILABLE",
            message="The platform validation workflow is unavailable.",
            status_code=503,
        )
    return service


def ensure_test_endpoint_enabled(request: Request) -> None:
    """Keep the disposable route closed in production unless explicitly enabled."""
    settings = cast(Settings, request.app.state.settings)
    if not settings.platform_test_endpoint_enabled:
        raise ApplicationError(
            code="PLATFORM_TEST_ENDPOINT_DISABLED",
            message="The platform validation endpoint is disabled.",
            status_code=404,
        )


@router.post(
    "/test-entities",
    response_model=CreateTestEntityResponse,
    status_code=201,
    dependencies=[Depends(ensure_test_endpoint_enabled)],
    responses={
        409: {"description": "Idempotency or optimistic-version conflict."},
        503: {"description": "Messaging workflow unavailable or timed out."},
    },
)
async def create_test_entity(
    body: CreateTestEntityRequest,
    request: Request,
    response: Response,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    service: Annotated[CreateTestEntityService, Depends(get_test_entity_service)],
) -> CreateTestEntityResponse:
    """Persist, emit, consume and audit one temporary entity automatically."""
    try:
        result = await service.execute(
            CreateTestEntityCommand(
                name=body.name,
                idempotency_key=idempotency_key,
                request_id=UUID(request.state.request_id),
                correlation_id=UUID(request.state.correlation_id),
                source_ip=request.client.host if request.client is not None else None,
            )
        )
    except (BrokerPublishError, BrokerUnavailableError) as error:
        raise ApplicationError(
            code="DEPENDENCY_UNAVAILABLE",
            message="RabbitMQ is unavailable for the validation workflow.",
            status_code=503,
            headers={"Retry-After": "1"},
        ) from error
    except TestEntityDeliveryTimeoutError as error:
        raise ApplicationError(
            code="ASYNC_PROCESSING_TIMEOUT",
            message="The event was not consumed within the request time budget.",
            status_code=503,
            headers={"Retry-After": "1"},
        ) from error

    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    return _response(result)


def _response(result: CreateTestEntityResult) -> CreateTestEntityResponse:
    return CreateTestEntityResponse(
        id=result.id,
        name=result.name,
        status=result.status,
        version=result.version,
        event_id=result.event_id,
        audit_event_ids=list(result.audit_event_ids),
        idempotency_replayed=result.idempotency_replayed,
    )


__all__ = ["router"]

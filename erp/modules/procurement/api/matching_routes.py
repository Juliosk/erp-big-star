"""Official REST endpoints for M6 three-way matching sessions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.api.matching_schemas import (
    CreateMatchingSessionRequest,
    MatchingExecutionResponse,
    MatchingSessionDetailResponse,
    MatchingSessionListResponse,
    MatchingSessionResponse,
)
from erp.modules.procurement.api.routes import resolve_security_context
from erp.modules.procurement.api.versioning import require_version
from erp.modules.procurement.application import (
    CreateMatchingSession,
    ExecuteMatchingSession,
    MatchingCommandService,
    MatchingLineReferenceInput,
    MatchingQueryService,
    ProcurementCommandMetadata,
)
from erp.modules.procurement.domain import ThreeWayMatchSessionStatus
from erp.platform.errors import ApplicationError

router = APIRouter(
    prefix="/api/v1/procurement/matching-sessions",
    tags=["procurement-matching"],
)


def get_matching_commands(request: Request) -> MatchingCommandService:
    service = getattr(request.app.state, "procurement_matching_commands", None)
    if not isinstance(service, MatchingCommandService):
        raise ApplicationError(
            code="PROCUREMENT_MATCHING_UNAVAILABLE",
            message="Three-way matching command services unavailable.",
            status_code=503,
        )
    return service


def get_matching_queries(request: Request) -> MatchingQueryService:
    service = getattr(request.app.state, "procurement_matching_queries", None)
    if not isinstance(service, MatchingQueryService):
        raise ApplicationError(
            code="PROCUREMENT_MATCHING_UNAVAILABLE",
            message="Three-way matching query services unavailable.",
            status_code=503,
        )
    return service


def require_idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if value is None or not value.strip() or len(value) > 255:
        raise ApplicationError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="Idempotency-Key must contain between 1 and 255 characters.",
            status_code=400,
        )
    return value.strip()


def _metadata(request: Request) -> ProcurementCommandMetadata:
    return ProcurementCommandMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=request.client.host if request.client is not None else None,
    )


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


@router.post("", status_code=201, response_model=MatchingSessionResponse)
async def create_matching_session(
    body: CreateMatchingSessionRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[MatchingCommandService, Depends(get_matching_commands)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> MatchingSessionResponse:
    value = await service.create(
        context,
        CreateMatchingSession(
            company_id=body.company_id,
            purchase_order_id=body.purchase_order_id,
            goods_receipt_ids=tuple(body.goods_receipt_ids),
            inbound_fiscal_document_ids=tuple(body.inbound_fiscal_document_ids),
            provisional_entry_id=body.provisional_entry_id,
            payable_id=body.payable_id,
            unit_price_variance_percentage=body.tolerance.unit_price_variance_percentage,
            quantity_variance_percentage=body.tolerance.quantity_variance_percentage,
            rounding_absolute_limit=body.tolerance.rounding_absolute_limit,
            tolerance_policy_version=body.tolerance.version,
            lines=tuple(MatchingLineReferenceInput(**item.model_dump()) for item in body.lines),
            idempotency_key=idempotency_key,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/procurement/matching-sessions/{value.id}?company_id={value.company_id}"
    )
    _etag(response, value.version)
    return MatchingSessionResponse.from_domain(value)


@router.get("/exceptions", response_model=MatchingSessionListResponse)
async def list_matching_exceptions(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[MatchingQueryService, Depends(get_matching_queries)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    purchase_order_id: UUID | None = None,
) -> MatchingSessionListResponse:
    value = await service.exception_queue(
        context,
        company_id,
        page=page,
        page_size=page_size,
        purchase_order_id=purchase_order_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return MatchingSessionListResponse.from_page(value)


@router.get("", response_model=MatchingSessionListResponse)
async def list_matching_sessions(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[MatchingQueryService, Depends(get_matching_queries)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: ThreeWayMatchSessionStatus | None = None,
    purchase_order_id: UUID | None = None,
) -> MatchingSessionListResponse:
    value = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        purchase_order_id=purchase_order_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return MatchingSessionListResponse.from_page(value)


@router.get("/{matching_session_id}", response_model=MatchingSessionDetailResponse)
async def get_matching_session(
    matching_session_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[MatchingQueryService, Depends(get_matching_queries)],
) -> MatchingSessionDetailResponse:
    value = await service.get(context, company_id, matching_session_id)
    _etag(response, value.session.version)
    return MatchingSessionDetailResponse.from_detail(value)


@router.post("/{matching_session_id}/execute", response_model=MatchingExecutionResponse)
async def execute_matching_session(
    matching_session_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[MatchingCommandService, Depends(get_matching_commands)],
    version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> MatchingExecutionResponse:
    value = await service.execute(
        context,
        ExecuteMatchingSession(
            company_id=company_id,
            matching_session_id=matching_session_id,
            expected_version=version,
            idempotency_key=idempotency_key,
            metadata=_metadata(request),
        ),
    )
    _etag(response, value.session.version)
    return MatchingExecutionResponse(
        session=MatchingSessionResponse.from_domain(value.session),
        event_ids=list(value.event_ids),
    )


__all__ = ["router"]

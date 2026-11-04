"""Official REST endpoints for M12 Cash Flow positions and scenarios."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.api.cash_flow_schemas import (
    CashFlowMutationResponse,
    CashFlowProjectionPageResponse,
    CashFlowProjectionResponse,
    CreateCashFlowProjectionRequest,
    SimulateCashFlowScenarioRequest,
)
from erp.modules.finance.api.routes import resolve_security_context
from erp.modules.finance.api.versioning import require_version
from erp.modules.finance.application import ComposeCashFlowProjection
from erp.modules.finance.application.cash_flow_api import (
    CashFlowApplicationService,
    CashFlowCommandMetadata,
    RefreshCashFlowProjection,
    SimulateCashFlowScenario,
    utc_now,
)
from erp.modules.finance.domain import (
    BusinessDayConvention,
    CashAmount,
    CashFlowCategory,
    CashFlowDateHorizon,
    CashFlowHorizonKind,
    CashFlowScenario,
    FinanceDomainError,
    ProjectionGranularity,
)
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/finance/cash-flow", tags=["finance-cash-flow"])


def get_service(request: Request) -> CashFlowApplicationService:
    service = getattr(request.app.state, "finance_cash_flow", None)
    if not isinstance(service, CashFlowApplicationService):
        raise ApplicationError(
            code="FINANCE_CASH_FLOW_UNAVAILABLE",
            message="Cash Flow services unavailable.",
            status_code=503,
        )
    return service


def _headers(
    response: Response,
    *,
    version: int | None = None,
    replayed: bool | None = None,
) -> None:
    response.headers["Cache-Control"] = "no-store"
    if version is not None:
        response.headers["ETag"] = f'"{version}"'
    if replayed is not None:
        response.headers["Idempotency-Replayed"] = str(replayed).lower()


def _metadata(request: Request) -> CashFlowCommandMetadata:
    return CashFlowCommandMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=None if request.client is None else request.client.host,
    )


@router.post("/projections", status_code=201, response_model=CashFlowMutationResponse)
async def create_projection(
    body: CreateCashFlowProjectionRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CashFlowApplicationService, Depends(get_service)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> CashFlowMutationResponse:
    try:
        scenario = CashFlowScenario(
            id=body.scenario.id,
            name=body.scenario.name,
            receivable_delay_days=body.scenario.receivable_delay_days,
            cost_variation_rate=body.scenario.cost_variation_rate,
            business_day_convention=BusinessDayConvention(
                body.scenario.business_day_convention
            ),
        )
        command = ComposeCashFlowProjection(
            projection_id=body.projection_id,
            company_id=body.company_id,
            as_of=body.as_of,
            calculated_at=utc_now(),
            horizon=CashFlowDateHorizon(body.as_of, body.horizon_end),
            granularity=ProjectionGranularity(body.granularity),
            minimum_reserve=CashAmount(body.minimum_reserve, body.currency),
            scenario=scenario,
            currency=body.currency,
        )
    except (FinanceDomainError, ValueError) as error:
        raise ApplicationError(
            code="VALIDATION_ERROR",
            message="Invalid Cash Flow projection request.",
            status_code=422,
        ) from error
    result = await service.project(
        context,
        command,
        idempotency_key=key,
        metadata=_metadata(request),
    )
    if result.idempotency_replayed:
        response.status_code = 200
    response.headers["Location"] = (
        f"/api/v1/finance/cash-flow/projections/{result.projection.id}"
        f"?company_id={result.projection.company_id}"
    )
    _headers(
        response,
        version=result.projection.version,
        replayed=result.idempotency_replayed,
    )
    return CashFlowMutationResponse.from_application(result)


@router.get(
    "/horizons/{horizon}", response_model=CashFlowProjectionPageResponse
)
async def list_horizon(
    horizon: CashFlowHorizonKind,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CashFlowApplicationService, Depends(get_service)],
    categories: Annotated[list[CashFlowCategory] | None, Query()] = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CashFlowProjectionPageResponse:
    values, selected_page, selected_size, has_more = await service.list_horizon(
        context,
        company_id,
        horizon=horizon,
        categories=tuple(categories or ()),
        page=page,
        page_size=page_size,
    )
    _headers(response)
    return CashFlowProjectionPageResponse(
        data=[CashFlowProjectionResponse.from_view(item) for item in values],
        page=selected_page,
        page_size=selected_size,
        has_more=has_more,
    )


@router.get(
    "/projections/{projection_id}", response_model=CashFlowProjectionResponse
)
async def get_projection(
    projection_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CashFlowApplicationService, Depends(get_service)],
    categories: Annotated[list[CashFlowCategory] | None, Query()] = None,
) -> CashFlowProjectionResponse:
    result = await service.get(
        context,
        company_id,
        projection_id,
        categories=tuple(categories or ()),
    )
    _headers(response, version=result.projection.version)
    return CashFlowProjectionResponse.from_view(result)


@router.post(
    "/projections/{projection_id}/recalculate",
    response_model=CashFlowMutationResponse,
)
async def recalculate_projection(
    projection_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CashFlowApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> CashFlowMutationResponse:
    result = await service.refresh(
        context,
        RefreshCashFlowProjection(
            company_id=company_id,
            projection_id=projection_id,
            expected_version=version,
            idempotency_key=key,
            calculated_at=utc_now(),
            metadata=_metadata(request),
        ),
    )
    _headers(
        response,
        version=result.projection.version,
        replayed=result.idempotency_replayed,
    )
    return CashFlowMutationResponse.from_application(result)


@router.post("/scenarios", response_model=CashFlowMutationResponse)
async def simulate_scenario(
    body: SimulateCashFlowScenarioRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CashFlowApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> CashFlowMutationResponse:
    try:
        convention = BusinessDayConvention(body.scenario.business_day_convention)
        command = SimulateCashFlowScenario(
            company_id=body.company_id,
            projection_id=body.projection_id,
            expected_version=version,
            scenario_id=body.scenario.id,
            name=body.scenario.name,
            receivable_delay_days=body.scenario.receivable_delay_days,
            cost_variation_rate=body.scenario.cost_variation_rate,
            business_day_convention=convention,
            idempotency_key=key,
            calculated_at=utc_now(),
            metadata=_metadata(request),
        )
        command.scenario()
    except (FinanceDomainError, ValueError) as error:
        raise ApplicationError(
            code="VALIDATION_ERROR",
            message="Invalid Cash Flow scenario request.",
            status_code=422,
        ) from error
    result = await service.simulate(context, command)
    _headers(
        response,
        version=result.base_version,
        replayed=result.idempotency_replayed,
    )
    return CashFlowMutationResponse.from_application(result)


__all__ = ["router"]

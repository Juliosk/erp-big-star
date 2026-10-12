"""Official tenant-scoped M12 payable REST endpoints."""

from datetime import date, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from erp.modules.admin.contracts import SecurityContext, SecurityContextResolver
from erp.modules.finance.api.schemas import (
    AdjustPayableRequest,
    CreatePayableRequest,
    PayableDetailResponse,
    PayableListResponse,
    PayableResponse,
    SchedulePayableRequest,
)
from erp.modules.finance.api.versioning import require_version
from erp.modules.finance.application import (
    AdjustPayable,
    ChangePayable,
    CreatePayable,
    InstallmentInput,
    PayableApplicationService,
    PayableCommandMetadata,
    SchedulePayable,
)
from erp.modules.finance.domain import PayableStatus
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/finance/payables", tags=["finance-payables"])
bearer = HTTPBearer(auto_error=False)


async def resolve_security_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SecurityContext:
    if credentials is None:
        raise ApplicationError(
            code="AUTHENTICATION_REQUIRED",
            message="A valid Bearer access token is required.",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    resolver = getattr(request.app.state, "security_context_resolver", None)
    if resolver is None:
        raise ApplicationError(
            code="AUTHENTICATION_UNAVAILABLE",
            message="The authentication service is unavailable.",
            status_code=503,
        )
    context = await cast(SecurityContextResolver, resolver).resolve(credentials.credentials)
    if context is None:
        raise ApplicationError(
            code="AUTHENTICATION_REQUIRED",
            message="A valid Bearer access token is required.",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return context


def get_service(request: Request) -> PayableApplicationService:
    service = getattr(request.app.state, "finance_payables", None)
    if not isinstance(service, PayableApplicationService):
        raise ApplicationError(
            code="FINANCE_PAYABLE_UNAVAILABLE",
            message="Payable services unavailable.",
            status_code=503,
        )
    return service


def _metadata(request: Request) -> PayableCommandMetadata:
    return PayableCommandMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=None if request.client is None else request.client.host,
    )


def _headers(response: Response, version: int, replayed: bool | None = None) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"
    if replayed is not None:
        response.headers["Idempotency-Replayed"] = str(replayed).lower()


@router.post("", status_code=201, response_model=PayableResponse)
async def create_payable(
    body: CreatePayableRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PayableApplicationService, Depends(get_service)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> PayableResponse:
    result = await service.create(
        context,
        CreatePayable(
            company_id=body.company_id,
            number=body.number,
            supplier_id=body.supplier_id,
            supplier_tax_id=body.supplier_tax_id,
            currency=body.currency,
            nominal_amount=body.nominal_amount,
            interest_amount=body.interest_amount,
            discount_amount=body.discount_amount,
            surcharge_amount=body.surcharge_amount,
            installments=tuple(InstallmentInput(**item.model_dump()) for item in body.installments),
            idempotency_key=key,
            metadata=_metadata(request),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/finance/payables/{result.payable.id}?company_id={body.company_id}"
    )
    _headers(response, result.payable.version, result.idempotency_replayed)
    return PayableResponse.from_domain(result.payable)


@router.get("", response_model=PayableListResponse)
async def list_payables(
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PayableApplicationService, Depends(get_service)],
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    supplier_id: UUID | None = None,
    status: PayableStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
) -> PayableListResponse:
    value = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        supplier_id=supplier_id,
        status=status,
        created_from=created_from,
        created_to=created_to,
        due_from=due_from,
        due_to=due_to,
    )
    response.headers["Cache-Control"] = "no-store"
    return PayableListResponse.from_page(value)


@router.get("/{payable_id}", response_model=PayableDetailResponse)
async def get_payable(
    payable_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PayableApplicationService, Depends(get_service)],
) -> PayableDetailResponse:
    value = await service.get(context, company_id, payable_id)
    _headers(response, value.payable.version)
    return PayableDetailResponse.from_detail(value)


@router.post("/{payable_id}/submit-for-approval", response_model=PayableResponse)
async def submit_for_approval(
    payable_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PayableApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
) -> PayableResponse:
    value = await service.submit(
        context, ChangePayable(company_id, payable_id, version, _metadata(request))
    )
    _headers(response, value.version)
    return PayableResponse.from_domain(value)


@router.patch("/{payable_id}/adjustments", response_model=PayableResponse)
async def adjust_payable(
    payable_id: UUID,
    company_id: UUID,
    body: AdjustPayableRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PayableApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
) -> PayableResponse:
    value = await service.adjust(
        context,
        AdjustPayable(
            company_id=company_id,
            payable_id=payable_id,
            expected_version=version,
            metadata=_metadata(request),
            discount_amount=body.discount_amount,
            surcharge_amount=body.surcharge_amount,
        ),
    )
    _headers(response, value.version)
    return PayableResponse.from_domain(value)


@router.post("/{payable_id}/schedule", response_model=PayableResponse)
async def schedule_payable(
    payable_id: UUID,
    company_id: UUID,
    body: SchedulePayableRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PayableApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> PayableResponse:
    result = await service.schedule(
        context,
        SchedulePayable(
            company_id=company_id,
            payable_id=payable_id,
            expected_version=version,
            metadata=_metadata(request),
            schedule_ids=tuple(body.schedule_ids),
            idempotency_key=key,
        ),
    )
    _headers(response, result.payable.version, result.idempotency_replayed)
    return PayableResponse.from_domain(result.payable)


__all__ = ["router"]

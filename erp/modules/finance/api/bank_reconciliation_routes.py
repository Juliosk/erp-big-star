"""Official REST endpoints for bank-statement reconciliation."""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.api.bank_reconciliation_schemas import (
    BankConciliationResponse,
    BankMovementListResponse,
    BankMovementQueueResponse,
    BankMovementResponse,
    BankStatementDetailResponse,
    BankStatementListResponse,
    MatchStatementRequest,
    ResolveMovementRequest,
)
from erp.modules.finance.api.routes import resolve_security_context
from erp.modules.finance.api.versioning import require_version
from erp.modules.finance.application import (
    BankReconciliationApplicationService,
    MatchBankStatement,
    ResolveBankMovement,
    UploadBankStatement,
)
from erp.modules.finance.domain import BankMovementStatus, BankStatementSource
from erp.platform.errors import ApplicationError

router = APIRouter(
    prefix="/api/v1/finance/reconciliation",
    tags=["finance-reconciliation"],
)
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def get_service(request: Request) -> BankReconciliationApplicationService:
    service = getattr(request.app.state, "finance_reconciliation", None)
    if not isinstance(service, BankReconciliationApplicationService):
        raise ApplicationError(
            code="FINANCE_RECONCILIATION_UNAVAILABLE",
            message="Bank reconciliation services unavailable.",
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


@router.post("/statements/upload", status_code=201, response_model=BankStatementDetailResponse)
async def upload_statement(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
    company_id: Annotated[UUID, Form()],
    bank_account_id: Annotated[UUID, Form()],
    source: Annotated[BankStatementSource, Form()],
    file: Annotated[UploadFile, File()],
    bank_code: Annotated[str | None, Form(max_length=20)] = None,
    account_reference: Annotated[str | None, Form(max_length=80)] = None,
) -> BankStatementDetailResponse:
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if not content or len(content) > _MAX_UPLOAD_BYTES:
        raise ApplicationError(
            code="INVALID_BANK_STATEMENT_UPLOAD",
            message="Bank statement must contain between 1 byte and 10 MiB.",
            status_code=422,
        )
    result = await service.upload(
        context,
        UploadBankStatement(
            company_id=company_id,
            bank_account_id=bank_account_id,
            source=source,
            content=content,
            original_file_name=file.filename,
            bank_code=bank_code,
            account_reference=account_reference,
        ),
    )
    if result.idempotency_replayed:
        response.status_code = 200
    response.headers["Location"] = (
        f"/api/v1/finance/reconciliation/statements/{result.statement.id}"
        f"?company_id={company_id}"
    )
    _headers(
        response,
        version=result.statement.version,
        replayed=result.idempotency_replayed,
    )
    return BankStatementDetailResponse.from_domain(result.statement)


@router.get("/statements", response_model=BankStatementListResponse)
async def list_statements(
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    bank_account_id: UUID | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
) -> BankStatementListResponse:
    value = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        bank_account_id=bank_account_id,
        period_from=period_from,
        period_to=period_to,
    )
    _headers(response)
    return BankStatementListResponse.from_page(value)


@router.get("/movements", response_model=BankMovementQueueResponse)
async def list_reconciliation_movements(
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
    status: BankMovementStatus | None = None,
    statement_id: UUID | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BankMovementQueueResponse:
    value = await service.list_movements(
        context,
        company_id,
        status=status,
        statement_id=statement_id,
        page=page,
        page_size=page_size,
    )
    _headers(response)
    return BankMovementQueueResponse.from_page(value)


@router.get("/statements/{statement_id}", response_model=BankStatementDetailResponse)
async def get_statement(
    statement_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
) -> BankStatementDetailResponse:
    value = await service.get(context, company_id, statement_id)
    _headers(response, version=value.version)
    return BankStatementDetailResponse.from_domain(value)


@router.get(
    "/statements/{statement_id}/movements",
    response_model=BankMovementListResponse,
)
async def list_movements(
    statement_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
    status: BankMovementStatus | None = None,
) -> BankMovementListResponse:
    statement, values = await service.movements(
        context,
        company_id,
        statement_id,
        status=status,
    )
    _headers(response, version=statement.version)
    return BankMovementListResponse(
        statement_id=statement.id,
        data=[BankMovementResponse.from_domain(item) for item in values],
    )


@router.post(
    "/statements/{statement_id}/match",
    response_model=BankConciliationResponse,
)
async def match_statement(
    statement_id: UUID,
    company_id: UUID,
    body: MatchStatementRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
) -> BankConciliationResponse:
    result = await service.match(
        context,
        MatchBankStatement(
            company_id=company_id,
            statement_id=statement_id,
            expected_version=version,
            mode=body.mode,
            occurred_at=datetime.now(UTC),
        ),
    )
    _headers(response, version=result.statement.version)
    return BankConciliationResponse.from_application(result)


@router.post(
    "/statements/{statement_id}/movements/{movement_id}/resolve",
    response_model=BankConciliationResponse,
)
async def resolve_movement(
    statement_id: UUID,
    movement_id: UUID,
    company_id: UUID,
    body: ResolveMovementRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[BankReconciliationApplicationService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
) -> BankConciliationResponse:
    result = await service.resolve(
        context,
        ResolveBankMovement(
            company_id=company_id,
            statement_id=statement_id,
            movement_id=movement_id,
            expected_version=version,
            mode=body.mode,
            occurred_at=datetime.now(UTC),
            candidate_id=body.candidate_id,
            justification=body.justification,
        ),
    )
    _headers(response, version=result.statement.version)
    return BankConciliationResponse.from_application(result)


__all__ = ["router"]

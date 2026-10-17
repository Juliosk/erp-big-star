"""Official REST endpoints for M12 Treasury payment batches and bank returns."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.api.routes import resolve_security_context
from erp.modules.finance.api.treasury_schemas import (
    CreateTreasuryBatchRequest,
    RemittanceRequest,
    TreasuryBatchDetailResponse,
    TreasuryBatchListResponse,
    TreasuryMutationResponse,
    TreasuryReturnResponse,
)
from erp.modules.finance.api.versioning import require_version
from erp.modules.finance.application import (
    ChangeTreasuryBatch,
    CreateTreasuryBatch,
    ProcessTreasuryReturn,
    TreasuryApplicationService,
    TreasuryCommandMetadata,
    TreasuryInstallmentInput,
    TreasuryQueryService,
)
from erp.modules.finance.domain import (
    BankAccountType,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    PaymentBatchStatus,
    PaymentExecutionMode,
)
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/finance/treasury", tags=["finance-treasury"])


def get_commands(request: Request) -> TreasuryApplicationService:
    service = getattr(request.app.state, "finance_treasury", None)
    if not isinstance(service, TreasuryApplicationService):
        raise ApplicationError(
            code="FINANCE_TREASURY_UNAVAILABLE",
            message="Treasury command services unavailable.",
            status_code=503,
        )
    return service


def get_queries(request: Request) -> TreasuryQueryService:
    service = getattr(request.app.state, "finance_treasury_queries", None)
    if not isinstance(service, TreasuryQueryService):
        raise ApplicationError(
            code="FINANCE_TREASURY_UNAVAILABLE",
            message="Treasury query services unavailable.",
            status_code=503,
        )
    return service


def _metadata(request: Request) -> TreasuryCommandMetadata:
    return TreasuryCommandMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=None if request.client is None else request.client.host,
    )


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


@router.post("/batches", status_code=201, response_model=TreasuryMutationResponse)
async def create_batch(
    body: CreateTreasuryBatchRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[TreasuryApplicationService, Depends(get_commands)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> TreasuryMutationResponse:
    try:
        installments = tuple(
            TreasuryInstallmentInput(
                item.installment_id,
                BeneficiaryBankAccount(
                    bank_code=item.beneficiary.bank_code,
                    branch_number=item.beneficiary.branch_number,
                    account_number=item.beneficiary.account_number,
                    account_digit=item.beneficiary.account_digit,
                    account_type=BankAccountType(item.beneficiary.account_type),
                    holder_name=item.beneficiary.holder_name,
                    holder_tax_id=item.beneficiary.holder_tax_id,
                ),
            )
            for item in body.installments
        )
        command = CreateTreasuryBatch(
            company_id=body.company_id,
            code=body.code,
            treasury_account_id=body.treasury_account_id,
            scheduled_date=body.scheduled_date,
            remittance_format=BankRemittanceFormat(body.remittance_format),
            execution_mode=PaymentExecutionMode(body.execution_mode),
            installments=installments,
            idempotency_key=key,
            metadata=_metadata(request),
        )
    except ValueError as error:
        raise ApplicationError(
            code="VALIDATION_ERROR",
            message="Invalid treasury batch request.",
            status_code=422,
        ) from error
    result = await service.create(context, command)
    response.headers["Location"] = (
        f"/api/v1/finance/treasury/batches/{result.batch.id}?company_id={result.batch.company_id}"
    )
    _headers(
        response,
        version=result.batch.version,
        replayed=result.idempotency_replayed,
    )
    return TreasuryMutationResponse.from_application(result)


@router.get("/batches", response_model=TreasuryBatchListResponse)
async def list_batches(
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[TreasuryQueryService, Depends(get_queries)],
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: PaymentBatchStatus | None = None,
    scheduled_from: date | None = None,
    scheduled_to: date | None = None,
) -> TreasuryBatchListResponse:
    result = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
    )
    _headers(response)
    return TreasuryBatchListResponse.from_application(result)


@router.get("/batches/{batch_id}", response_model=TreasuryBatchDetailResponse)
async def get_batch(
    batch_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[TreasuryQueryService, Depends(get_queries)],
) -> TreasuryBatchDetailResponse:
    result = await service.get(context, company_id, batch_id)
    _headers(response, version=result.batch.version)
    return TreasuryBatchDetailResponse.from_application(result)


@router.post("/batches/{batch_id}/dry-run", response_model=TreasuryMutationResponse)
async def dry_run(
    batch_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[TreasuryApplicationService, Depends(get_commands)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> TreasuryMutationResponse:
    result = await service.dry_run(
        context,
        ChangeTreasuryBatch(
            company_id,
            batch_id,
            version,
            key,
            metadata=_metadata(request),
        ),
    )
    _headers(
        response,
        version=result.batch.version,
        replayed=result.idempotency_replayed,
    )
    return TreasuryMutationResponse.from_application(result)


@router.post("/batches/{batch_id}/remittance", response_model=TreasuryMutationResponse)
async def generate_remittance(
    batch_id: UUID,
    company_id: UUID,
    body: RemittanceRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[TreasuryApplicationService, Depends(get_commands)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> TreasuryMutationResponse:
    result = await service.remittance(
        context,
        ChangeTreasuryBatch(
            company_id,
            batch_id,
            version,
            key,
            workflow_instance_id=body.workflow_instance_id,
            metadata=_metadata(request),
        ),
    )
    if result.remittance is None:
        response.status_code = 202
    _headers(
        response,
        version=result.batch.version,
        replayed=result.idempotency_replayed,
    )
    return TreasuryMutationResponse.from_application(result)


@router.post("/returns", response_model=TreasuryReturnResponse)
async def process_bank_return(
    company_id: UUID,
    remittance_format: BankRemittanceFormat,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[TreasuryApplicationService, Depends(get_commands)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> TreasuryReturnResponse:
    content = await request.body()
    if not content or len(content) > 10 * 1024 * 1024:
        raise ApplicationError(
            code="INVALID_BANK_RETURN",
            message="Bank return must contain between 1 byte and 10 MiB.",
            status_code=422,
        )
    result = await service.process_return(
        context,
        ProcessTreasuryReturn(
            company_id,
            remittance_format,
            content,
            key,
            _metadata(request),
        ),
    )
    _headers(response, replayed=result.idempotency_replayed)
    return TreasuryReturnResponse.from_application(result)


__all__ = ["router"]

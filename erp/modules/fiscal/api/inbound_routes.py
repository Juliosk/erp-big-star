"""Tenant-scoped REST boundary for inbound NF-e and MDE."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.api.inbound_schemas import (
    InboundFiscalDocumentResponse,
    InboundFiscalListResponse,
    ManifestInboundRequest,
)
from erp.modules.fiscal.api.reconciliation_schemas import (
    FiscalReceivingReconciliationResponse,
    ReconcileFiscalReceivingRequest,
)
from erp.modules.fiscal.api.routes import resolve_security_context
from erp.modules.fiscal.api.versioning import require_version
from erp.modules.fiscal.application import (
    FiscalReceivingReconciliationService,
    ReconcileFiscalReceiving,
    ReconciliationMetadata,
)
from erp.modules.fiscal.application.inbound_documents import InboundFiscalDocumentService
from erp.modules.fiscal.domain import RecipientManifestationStatus
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/fiscal/inbound-documents", tags=["fiscal-inbound"])


def get_service(request: Request) -> InboundFiscalDocumentService:
    service = getattr(request.app.state, "inbound_fiscal_documents", None)
    if not isinstance(service, InboundFiscalDocumentService):
        raise ApplicationError(
            code="FISCAL_INBOUND_UNAVAILABLE",
            message="Inbound fiscal services unavailable.",
            status_code=503,
        )
    return service


def get_reconciliation_service(request: Request) -> FiscalReceivingReconciliationService:
    service = getattr(request.app.state, "fiscal_receiving_reconciliation", None)
    if not isinstance(service, FiscalReceivingReconciliationService):
        raise ApplicationError(
            code="FISCAL_RECONCILIATION_UNAVAILABLE",
            message="Fiscal receiving reconciliation is unavailable.",
            status_code=503,
        )
    return service


def _headers(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


@router.post("/upload", status_code=201, response_model=InboundFiscalDocumentResponse)
async def upload(
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InboundFiscalDocumentService, Depends(get_service)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> InboundFiscalDocumentResponse:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type not in {"application/xml", "text/xml"}:
        raise ApplicationError(
            code="UNSUPPORTED_MEDIA_TYPE",
            message="Inbound upload requires application/xml or text/xml.",
            status_code=415,
        )
    result = await service.upload(context, company_id, await request.body(), key)
    _headers(response, result.document.version)
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Location"] = (
        f"/api/v1/fiscal/inbound-documents/{result.document.id}?company_id={company_id}"
    )
    return InboundFiscalDocumentResponse.from_domain(result.document)


@router.post("/{document_id}/manifest", response_model=InboundFiscalDocumentResponse)
async def manifest(
    document_id: UUID,
    company_id: UUID,
    body: ManifestInboundRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InboundFiscalDocumentService, Depends(get_service)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> InboundFiscalDocumentResponse:
    result = await service.manifest(
        context, company_id, document_id, version, body.event_type, body.reason, key
    )
    _headers(response, result.document.version)
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    return InboundFiscalDocumentResponse.from_domain(result.document)


@router.post(
    "/{document_id}/reconcile",
    response_model=FiscalReceivingReconciliationResponse,
)
async def reconcile(
    document_id: UUID,
    company_id: UUID,
    body: ReconcileFiscalReceivingRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalReceivingReconciliationService, Depends(get_reconciliation_service)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> FiscalReceivingReconciliationResponse:
    result = await service.reconcile(
        context,
        ReconcileFiscalReceiving(
            company_id=company_id,
            inbound_fiscal_document_id=document_id,
            goods_receipt_id=body.goods_receipt_id,
            expected_inbound_version=version,
            line_mappings=body.mappings(),
            price_tolerance=body.price_tolerance,
            idempotency_key=key,
            metadata=ReconciliationMetadata(
                request_id=UUID(request.state.request_id),
                correlation_id=UUID(request.state.correlation_id),
                source_ip=None if request.client is None else request.client.host,
            ),
        ),
    )
    _headers(response, result.reconciliation.version)
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    return FiscalReceivingReconciliationResponse.from_domain(result.reconciliation)


@router.get(
    "/{document_id}/reconcile",
    response_model=FiscalReceivingReconciliationResponse,
)
async def get_reconciliation(
    document_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalReceivingReconciliationService, Depends(get_reconciliation_service)],
) -> FiscalReceivingReconciliationResponse:
    value = await service.get(context, company_id, document_id)
    if value is None:
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND",
            message="Fiscal receiving reconciliation not found.",
            status_code=404,
        )
    _headers(response, value.version)
    return FiscalReceivingReconciliationResponse.from_domain(value)


@router.get("", response_model=InboundFiscalListResponse)
async def list_documents(
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InboundFiscalDocumentService, Depends(get_service)],
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    access_key: Annotated[str | None, Query(min_length=44, max_length=44)] = None,
    supplier_tax_id: str | None = None,
    mde_status: RecipientManifestationStatus | None = None,
    issued_from: datetime | None = None,
    issued_to: datetime | None = None,
) -> InboundFiscalListResponse:
    value = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        access_key=access_key,
        supplier_tax_id=supplier_tax_id,
        mde_status=mde_status,
        issued_from=issued_from,
        issued_to=issued_to,
    )
    response.headers["Cache-Control"] = "no-store"
    return InboundFiscalListResponse.from_page(value)


@router.get("/{document_id}", response_model=InboundFiscalDocumentResponse)
async def get_document(
    document_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InboundFiscalDocumentService, Depends(get_service)],
) -> InboundFiscalDocumentResponse:
    value = await service.get(context, company_id, document_id)
    _headers(response, value.version)
    return InboundFiscalDocumentResponse.from_domain(value)


__all__ = ["router"]

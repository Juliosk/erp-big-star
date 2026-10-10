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
from erp.modules.fiscal.api.routes import resolve_security_context
from erp.modules.fiscal.api.versioning import require_version
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

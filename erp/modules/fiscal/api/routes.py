"""Official M11 fiscal document REST endpoints."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from erp.modules.admin.contracts import SecurityContext, SecurityContextResolver
from erp.modules.fiscal.api.schemas import (
    CreateFiscalDocumentRequest,
    FiscalDocumentListResponse,
    FiscalDocumentResponse,
)
from erp.modules.fiscal.api.versioning import require_version
from erp.modules.fiscal.application import FiscalDocumentService, IssueFiscalDocument
from erp.modules.fiscal.domain import FiscalDocumentModel, FiscalDocumentStatus
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/fiscal/documents", tags=["fiscal-documents"])
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


def get_fiscal_service(request: Request) -> FiscalDocumentService:
    service = getattr(request.app.state, "fiscal_documents", None)
    if not isinstance(service, FiscalDocumentService):
        raise ApplicationError(
            code="FISCAL_SERVICE_UNAVAILABLE",
            message="Fiscal document services unavailable.",
            status_code=503,
        )
    return service


@router.post("", status_code=201, response_model=FiscalDocumentResponse)
async def create_document(
    body: CreateFiscalDocumentRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalDocumentService, Depends(get_fiscal_service)],
) -> FiscalDocumentResponse:
    document = await service.create(context, body.to_command())
    response.headers["Location"] = (
        f"/api/v1/fiscal/documents/{document.id}?company_id={document.company_id}"
    )
    _version_headers(response, document.version)
    return FiscalDocumentResponse.from_domain(document)


@router.post("/{document_id}/issue", status_code=202, response_model=FiscalDocumentResponse)
async def issue_document(
    document_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalDocumentService, Depends(get_fiscal_service)],
    version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> FiscalDocumentResponse:
    result = await service.issue(
        context,
        IssueFiscalDocument(company_id, document_id, version, idempotency_key),
    )
    _version_headers(response, result.document.version)
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    return FiscalDocumentResponse.from_domain(result.document)


@router.get("", response_model=FiscalDocumentListResponse)
async def list_documents(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalDocumentService, Depends(get_fiscal_service)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: FiscalDocumentStatus | None = None,
    access_key: Annotated[str | None, Query(min_length=1, max_length=44)] = None,
    model: FiscalDocumentModel | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> FiscalDocumentListResponse:
    result = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        access_key=access_key,
        model=model,
        created_from=created_from,
        created_to=created_to,
    )
    response.headers["Cache-Control"] = "no-store"
    return FiscalDocumentListResponse.from_page(result)


@router.get("/{document_id}", response_model=FiscalDocumentResponse)
async def get_document(
    document_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalDocumentService, Depends(get_fiscal_service)],
) -> FiscalDocumentResponse:
    document = await service.get(context, company_id, document_id)
    _version_headers(response, document.version)
    return FiscalDocumentResponse.from_domain(document)


def _version_headers(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


__all__ = ["router"]

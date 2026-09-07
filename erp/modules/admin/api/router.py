"""HTTP boundary for M1 corporate administration."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from erp.modules.admin.application import (
    CompanyView,
    ListCompaniesService,
    SecurityContext,
    SecurityContextResolver,
)
from erp.modules.admin.domain import CorporateStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/admin", tags=["admin-corporate"])
bearer = HTTPBearer(auto_error=False)


class CompanyResponse(BaseModel):
    id: UUID
    group_id: UUID
    code: str
    legal_name: str
    trade_name: str | None
    tax_id: str
    timezone: str
    status: CorporateStatus
    version: int


class CompanyListResponse(BaseModel):
    items: list[CompanyResponse]


async def resolve_security_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SecurityContext:
    """Validate Bearer authentication through the composed security adapter."""
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


def get_company_query_service(request: Request) -> ListCompaniesService:
    service = getattr(request.app.state, "company_query_service", None)
    if not isinstance(service, ListCompaniesService):
        raise ApplicationError(
            code="CORPORATE_QUERY_UNAVAILABLE",
            message="The corporate directory is unavailable.",
            status_code=503,
        )
    return service


@router.get(
    "/companies",
    response_model=CompanyListResponse,
    responses={
        401: {"description": "Bearer token missing or invalid."},
        403: {"description": "Permission or scope denied."},
        503: {"description": "Security or corporate directory unavailable."},
    },
)
async def list_companies(
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ListCompaniesService, Depends(get_company_query_service)],
    status: Annotated[CorporateStatus | None, Query()] = None,
) -> CompanyListResponse:
    """List legal companies without exposing records outside current scopes."""
    companies = await service.execute(context, status=status)
    return CompanyListResponse(items=[_company_response(company) for company in companies])


def _company_response(company: CompanyView) -> CompanyResponse:
    return CompanyResponse(
        id=company.id,
        group_id=company.group_id,
        code=company.code,
        legal_name=company.legal_name,
        trade_name=company.trade_name,
        tax_id=company.tax_id,
        timezone=company.timezone,
        status=company.status,
        version=company.version,
    )


__all__ = ["router"]

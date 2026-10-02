"""Official M6 supplier REST endpoints."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from erp.modules.admin.contracts import SecurityContext, SecurityContextResolver
from erp.modules.procurement.api.schemas import (
    CreateSupplierRequest,
    SupplierListResponse,
    SupplierResponse,
    UpdateSupplierRequest,
)
from erp.modules.procurement.api.versioning import require_version
from erp.modules.procurement.application.suppliers import (
    CreateSupplier,
    SupplierService,
    UpdateSupplier,
)
from erp.modules.procurement.domain import SupplierStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/procurement/suppliers", tags=["procurement-suppliers"])
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


def get_supplier_service(request: Request) -> SupplierService:
    service = getattr(request.app.state, "procurement_suppliers", None)
    if not isinstance(service, SupplierService):
        raise ApplicationError(
            code="PROCUREMENT_SUPPLIER_UNAVAILABLE",
            message="Supplier services unavailable.",
            status_code=503,
        )
    return service


@router.post("", status_code=201, response_model=SupplierResponse)
async def create_supplier(
    body: CreateSupplierRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SupplierService, Depends(get_supplier_service)],
) -> SupplierResponse:
    supplier = await service.create(
        context,
        CreateSupplier(
            company_id=body.company_id,
            kind=body.kind,
            identity_kind=body.identity_kind,
            identity_value=body.identity_value,
            identity_country_code=body.identity_country_code,
            legal_name=body.legal_name,
            trade_name=body.trade_name,
            sites=tuple(site.to_input() for site in body.sites),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/procurement/suppliers/{supplier.id}?company_id={supplier.company_id}"
    )
    response.headers["ETag"] = f'"{supplier.version}"'
    response.headers["Cache-Control"] = "no-store"
    return SupplierResponse.from_domain(supplier)


@router.get("", response_model=SupplierListResponse)
async def list_suppliers(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SupplierService, Depends(get_supplier_service)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: SupplierStatus | None = None,
    document: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
) -> SupplierListResponse:
    result = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        document=document,
    )
    response.headers["Cache-Control"] = "no-store"
    return SupplierListResponse.from_page(result)


@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SupplierService, Depends(get_supplier_service)],
) -> SupplierResponse:
    supplier = await service.get(context, company_id, supplier_id)
    response.headers["ETag"] = f'"{supplier.version}"'
    response.headers["Cache-Control"] = "no-store"
    return SupplierResponse.from_domain(supplier)


@router.patch("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    company_id: UUID,
    body: UpdateSupplierRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SupplierService, Depends(get_supplier_service)],
    version: Annotated[int, Depends(require_version)],
) -> SupplierResponse:
    supplier = await service.update(
        context,
        UpdateSupplier(
            company_id=company_id,
            supplier_id=supplier_id,
            expected_version=version,
            legal_name=body.legal_name,
            trade_name=body.trade_name,
            clear_trade_name="trade_name" in body.model_fields_set and body.trade_name is None,
            status=body.status,
        ),
    )
    response.headers["ETag"] = f'"{supplier.version}"'
    response.headers["Cache-Control"] = "no-store"
    return SupplierResponse.from_domain(supplier)


__all__ = ["router"]

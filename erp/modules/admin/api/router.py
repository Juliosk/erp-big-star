"""HTTP boundary for M1 corporate administration."""

import re
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from erp.modules.admin.application import (
    BranchView,
    CompanyView,
    CorporateCreationService,
    CorporateHierarchyService,
    CreateBranchCommand,
    CreateCompanyCommand,
    ListCompaniesService,
    RequestMetadata,
    SecurityContext,
    SecurityContextResolver,
    UpdateBranchCommand,
    UpdateCompanyCommand,
)
from erp.modules.admin.domain import CorporateStatus
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/admin", tags=["admin-corporate"])
bearer = HTTPBearer(auto_error=False)
IF_MATCH_PATTERN = re.compile(r'^"([1-9][0-9]*)"$')


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


class BranchResponse(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    tax_id: str
    timezone: str
    status: CorporateStatus
    version: int


class CreateCompanyRequest(BaseModel):
    group_id: UUID
    code: str = Field(min_length=2, max_length=30)
    legal_name: str = Field(min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    tax_id: str = Field(min_length=14, max_length=18)
    timezone: str = Field(min_length=1, max_length=100)


class CreateBranchRequest(BaseModel):
    company_id: UUID
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    tax_id: str = Field(min_length=14, max_length=18)
    timezone: str = Field(min_length=1, max_length=100)


class CompanyCreationResponse(BaseModel):
    company: CompanyResponse
    event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool


class BranchCreationResponse(BaseModel):
    branch: BranchResponse
    event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool


class UpdateCompanyRequest(BaseModel):
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    status: CorporateStatus | None = None


class UpdateBranchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    status: CorporateStatus | None = None


class CompanyUpdateResponse(BaseModel):
    company: CompanyResponse
    event_id: UUID
    audit_event_id: UUID


class BranchUpdateResponse(BaseModel):
    branch: BranchResponse
    event_id: UUID
    audit_event_id: UUID


class EconomicGroupResponse(BaseModel):
    id: UUID
    code: str
    name: str
    status: CorporateStatus
    version: int


class EconomicGroupListResponse(BaseModel):
    items: list[EconomicGroupResponse]


class BranchListResponse(BaseModel):
    items: list[BranchResponse]


class CompanySelectorCompanyResponse(BaseModel):
    company: CompanyResponse
    branches: list[BranchResponse]


class CompanySelectorGroupResponse(BaseModel):
    group: EconomicGroupResponse
    companies: list[CompanySelectorCompanyResponse]


class CompanySelectorResponse(BaseModel):
    groups: list[CompanySelectorGroupResponse]


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


def get_corporate_creation_service(request: Request) -> CorporateCreationService:
    service = getattr(request.app.state, "corporate_creation_service", None)
    if not isinstance(service, CorporateCreationService):
        raise ApplicationError(
            code="CORPORATE_COMMAND_UNAVAILABLE",
            message="Corporate commands are unavailable.",
            status_code=503,
        )
    return service


def get_corporate_hierarchy_service(request: Request) -> CorporateHierarchyService:
    service = getattr(request.app.state, "corporate_hierarchy_service", None)
    if not isinstance(service, CorporateHierarchyService):
        raise ApplicationError(
            code="CORPORATE_QUERY_UNAVAILABLE",
            message="The corporate hierarchy is unavailable.",
            status_code=503,
        )
    return service


async def require_if_match(
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> int:
    """Require the quoted positive aggregate version used by critical PATCHes."""
    if if_match is None:
        raise ApplicationError(
            code="PRECONDITION_REQUIRED",
            message="If-Match with the current quoted version is required.",
            status_code=428,
        )
    matched = IF_MATCH_PATTERN.fullmatch(if_match.strip())
    if matched is None:
        raise ApplicationError(
            code="INVALID_IF_MATCH",
            message='If-Match must contain a quoted positive version, for example "7".',
            status_code=400,
        )
    return int(matched.group(1))


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


@router.post(
    "/companies",
    response_model=CompanyCreationResponse,
    status_code=201,
    responses={403: {"description": "Permission or group scope denied."}},
)
async def create_company(
    body: CreateCompanyRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateCreationService, Depends(get_corporate_creation_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> CompanyCreationResponse:
    result = await service.create_company(
        context,
        CreateCompanyCommand(
            group_id=body.group_id,
            code=body.code,
            legal_name=body.legal_name,
            trade_name=body.trade_name,
            tax_id=body.tax_id,
            timezone=body.timezone,
            idempotency_key=idempotency_key,
            metadata=_metadata(request),
        ),
    )
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Location"] = f"/api/v1/admin/companies/{result.company.id}"
    response.headers["ETag"] = f'"{result.company.version}"'
    return CompanyCreationResponse(
        company=_company_response(result.company),
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
        idempotency_replayed=result.idempotency_replayed,
    )


@router.post(
    "/branches",
    response_model=BranchCreationResponse,
    status_code=201,
    responses={403: {"description": "Permission or company/group scope denied."}},
)
async def create_branch(
    body: CreateBranchRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateCreationService, Depends(get_corporate_creation_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> BranchCreationResponse:
    result = await service.create_branch(
        context,
        CreateBranchCommand(
            company_id=body.company_id,
            code=body.code,
            name=body.name,
            tax_id=body.tax_id,
            timezone=body.timezone,
            idempotency_key=idempotency_key,
            metadata=_metadata(request),
        ),
    )
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Location"] = f"/api/v1/admin/branches/{result.branch.id}"
    response.headers["ETag"] = f'"{result.branch.version}"'
    return BranchCreationResponse(
        branch=BranchResponse(
            id=result.branch.id,
            company_id=result.branch.company_id,
            code=result.branch.code,
            name=result.branch.name,
            tax_id=result.branch.tax_id,
            timezone=result.branch.timezone,
            status=result.branch.status,
            version=result.branch.version,
        ),
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
        idempotency_replayed=result.idempotency_replayed,
    )


@router.patch(
    "/companies/{company_id}",
    response_model=CompanyUpdateResponse,
    responses={
        409: {"description": "The If-Match version is stale."},
        428: {"description": "If-Match is required."},
    },
)
async def update_company(
    company_id: UUID,
    body: UpdateCompanyRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateCreationService, Depends(get_corporate_creation_service)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> CompanyUpdateResponse:
    result = await service.update_company(
        context,
        UpdateCompanyCommand(
            company_id=company_id,
            expected_version=expected_version,
            legal_name=body.legal_name,
            trade_name=body.trade_name,
            trade_name_supplied="trade_name" in body.model_fields_set,
            timezone=body.timezone,
            status=body.status,
            metadata=_metadata(request),
        ),
    )
    response.headers["ETag"] = f'"{result.company.version}"'
    return CompanyUpdateResponse(
        company=_company_response(result.company),
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
    )


@router.patch(
    "/branches/{branch_id}",
    response_model=BranchUpdateResponse,
    responses={
        409: {"description": "The If-Match version is stale."},
        428: {"description": "If-Match is required."},
    },
)
async def update_branch(
    branch_id: UUID,
    body: UpdateBranchRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateCreationService, Depends(get_corporate_creation_service)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> BranchUpdateResponse:
    result = await service.update_branch(
        context,
        UpdateBranchCommand(
            branch_id=branch_id,
            expected_version=expected_version,
            name=body.name,
            timezone=body.timezone,
            status=body.status,
            metadata=_metadata(request),
        ),
    )
    response.headers["ETag"] = f'"{result.branch.version}"'
    return BranchUpdateResponse(
        branch=BranchResponse(
            id=result.branch.id,
            company_id=result.branch.company_id,
            code=result.branch.code,
            name=result.branch.name,
            tax_id=result.branch.tax_id,
            timezone=result.branch.timezone,
            status=result.branch.status,
            version=result.branch.version,
        ),
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
    )


@router.get("/economic-groups", response_model=EconomicGroupListResponse)
async def list_economic_groups(
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateHierarchyService, Depends(get_corporate_hierarchy_service)],
    status: Annotated[CorporateStatus | None, Query()] = None,
) -> EconomicGroupListResponse:
    groups = await service.list_groups(context, status=status)
    return EconomicGroupListResponse(
        items=[
            EconomicGroupResponse(
                id=group.id,
                code=group.code,
                name=group.name,
                status=group.status,
                version=group.version,
            )
            for group in groups
        ]
    )


@router.get("/companies/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateHierarchyService, Depends(get_corporate_hierarchy_service)],
) -> CompanyResponse:
    company = await service.get_company(context, company_id)
    response.headers["ETag"] = f'"{company.version}"'
    return _company_response(company)


@router.get("/branches", response_model=BranchListResponse)
async def list_branches(
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateHierarchyService, Depends(get_corporate_hierarchy_service)],
    company_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[CorporateStatus | None, Query()] = None,
) -> BranchListResponse:
    branches = await service.list_branches(context, company_id=company_id, status=status)
    return BranchListResponse(items=[_branch_response(branch) for branch in branches])


@router.get("/company-selector", response_model=CompanySelectorResponse)
async def get_company_selector(
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CorporateHierarchyService, Depends(get_corporate_hierarchy_service)],
) -> CompanySelectorResponse:
    selector = await service.company_selector(context)
    return CompanySelectorResponse(
        groups=[
            CompanySelectorGroupResponse(
                group=EconomicGroupResponse(
                    id=group_node.group.id,
                    code=group_node.group.code,
                    name=group_node.group.name,
                    status=group_node.group.status,
                    version=group_node.group.version,
                ),
                companies=[
                    CompanySelectorCompanyResponse(
                        company=_company_response(company_node.company),
                        branches=[_branch_response(branch) for branch in company_node.branches],
                    )
                    for company_node in group_node.companies
                ],
            )
            for group_node in selector.groups
        ]
    )


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


def _branch_response(branch: BranchView) -> BranchResponse:
    return BranchResponse(
        id=branch.id,
        company_id=branch.company_id,
        code=branch.code,
        name=branch.name,
        tax_id=branch.tax_id,
        timezone=branch.timezone,
        status=branch.status,
        version=branch.version,
    )


def _metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=request.client.host if request.client is not None else None,
    )


__all__ = ["router"]

"""Customer group and segmentation HTTP endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.api.creation import metadata
from erp.modules.customer.api.schemas import (
    CustomerGroupAssignmentResponse,
    CustomerGroupListResponse,
    CustomerGroupResponse,
    PageMetadata,
)
from erp.modules.customer.application.groups import (
    AssignCustomerGroup,
    CreateCustomerGroup,
    CustomerGroupService,
)
from erp.platform.errors import ApplicationError

router = APIRouter(tags=["customer-core"])


class CreateCustomerGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class AssignCustomerGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    customer_group_id: UUID


def get_groups(request: Request) -> CustomerGroupService:
    service = getattr(request.app.state, "customer_groups", None)
    if not isinstance(service, CustomerGroupService):
        raise ApplicationError(
            code="CUSTOMER_GROUP_UNAVAILABLE",
            message="Customer group commands unavailable.",
            status_code=503,
        )
    return service


@router.get("/api/v1/customer-groups", response_model=CustomerGroupListResponse)
async def list_customer_groups(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerGroupService, Depends(get_groups)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    active: bool | None = None,
) -> CustomerGroupListResponse:
    result = await service.list_groups(
        context, company_id, page=page, page_size=page_size, active=active
    )
    response.headers["Cache-Control"] = "no-store"
    return CustomerGroupListResponse(
        data=[CustomerGroupResponse.from_domain(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.post("/api/v1/customer-groups", status_code=201, response_model=CustomerGroupResponse)
async def create_customer_group(
    body: CreateCustomerGroupRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerGroupService, Depends(get_groups)],
) -> CustomerGroupResponse:
    group = await service.create_group(
        context,
        CreateCustomerGroup(
            company_id=body.company_id,
            code=body.code,
            name=body.name,
            description=body.description,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/customer-groups/{group.id}?company_id={group.company_id}"
    )
    response.headers["ETag"] = f'"{group.version}"'
    response.headers["Cache-Control"] = "no-store"
    return CustomerGroupResponse.from_domain(group)


@router.post(
    "/api/v1/customers/{customer_id}/groups",
    status_code=201,
    response_model=CustomerGroupAssignmentResponse,
)
async def assign_customer_group(
    customer_id: UUID,
    body: AssignCustomerGroupRequest,
    request: Request,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerGroupService, Depends(get_groups)],
) -> CustomerGroupAssignmentResponse:
    result = await service.assign(
        context,
        AssignCustomerGroup(
            company_id=body.company_id,
            customer_id=customer_id,
            customer_group_id=body.customer_group_id,
            metadata=metadata(request),
        ),
    )
    return CustomerGroupAssignmentResponse(
        id=result.member.id,
        company_id=result.member.company_id,
        customer_id=result.member.customer_id,
        customer_group_id=result.member.customer_group_id,
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
    )


__all__ = ["router"]

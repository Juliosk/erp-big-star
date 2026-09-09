"""Duplicate detection and merge request HTTP endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.api.creation import metadata
from erp.modules.customer.api.schemas import (
    CustomerDuplicateCandidateResponse,
    CustomerDuplicateListResponse,
    CustomerMergeRequestResponse,
)
from erp.modules.customer.application.duplicates import (
    CustomerDuplicateService,
    RequestCustomerMerge,
)
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/customers", tags=["customer-core"])


class RequestCustomerMergeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    candidate_customer_id: UUID
    surviving_customer_id: UUID
    reason: str = Field(min_length=1, max_length=500)


def get_duplicates(request: Request) -> CustomerDuplicateService:
    service = getattr(request.app.state, "customer_duplicates", None)
    if not isinstance(service, CustomerDuplicateService):
        raise ApplicationError(
            code="CUSTOMER_DUPLICATE_UNAVAILABLE",
            message="Customer duplicate services unavailable.",
            status_code=503,
        )
    return service


@router.post("/{customer_id}/duplicates/detect", response_model=CustomerDuplicateListResponse)
async def detect_customer_duplicates(
    customer_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerDuplicateService, Depends(get_duplicates)],
) -> CustomerDuplicateListResponse:
    candidates = await service.detect(context, company_id, customer_id)
    response.headers["Cache-Control"] = "no-store"
    return CustomerDuplicateListResponse(
        data=[CustomerDuplicateCandidateResponse.from_domain(candidate) for candidate in candidates]
    )


@router.post(
    "/{customer_id}/merge-requests",
    status_code=201,
    response_model=CustomerMergeRequestResponse,
)
async def request_customer_merge(
    customer_id: UUID,
    body: RequestCustomerMergeBody,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerDuplicateService, Depends(get_duplicates)],
) -> CustomerMergeRequestResponse:
    result = await service.request_merge(
        context,
        RequestCustomerMerge(
            company_id=body.company_id,
            source_customer_id=customer_id,
            candidate_customer_id=body.candidate_customer_id,
            surviving_customer_id=body.surviving_customer_id,
            reason=body.reason,
            metadata=metadata(request),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/customers/{customer_id}/merge-requests/{result.merge_request.id}"
        f"?company_id={result.merge_request.company_id}"
    )
    response.headers["ETag"] = f'"{result.merge_request.version}"'
    response.headers["Cache-Control"] = "no-store"
    return CustomerMergeRequestResponse.from_domain(
        result.merge_request, event_id=result.event_id, audit_event_id=result.audit_event_id
    )


__all__ = ["router"]

"""PATCH changes mutable M14 master data only; identity and scope are fixed."""

from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.api.creation import CustomerCommandResponse, metadata
from erp.modules.customer.api.versioning import require_version
from erp.modules.customer.application.updates import CustomerUpdateService, UpdateCustomer
from erp.modules.customer.domain import CustomerStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/customers", tags=["customer-core"])


class UpdateCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    status: CustomerStatus | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls_except_trade_name(self) -> Self:
        if "legal_name" in self.model_fields_set and self.legal_name is None:
            raise ValueError("legal_name cannot be null.")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null.")
        return self


def get_updates(request: Request) -> CustomerUpdateService:
    service = getattr(request.app.state, "customer_updates", None)
    if not isinstance(service, CustomerUpdateService):
        raise ApplicationError(
            code="CUSTOMER_COMMAND_UNAVAILABLE",
            message="Customer commands unavailable.",
            status_code=503,
        )
    return service


@router.patch("/{customer_id}", response_model=CustomerCommandResponse)
async def update_customer(
    customer_id: UUID,
    company_id: UUID,
    body: UpdateCustomerRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerUpdateService, Depends(get_updates)],
    version: Annotated[int, Depends(require_version)],
) -> CustomerCommandResponse:
    result = await service.update(
        context,
        UpdateCustomer(
            company_id=company_id,
            customer_id=customer_id,
            expected_version=version,
            metadata=metadata(request),
            legal_name=body.legal_name,
            trade_name=body.trade_name,
            clear_trade_name="trade_name" in body.model_fields_set and body.trade_name is None,
            status=body.status,
        ),
    )
    response.headers["ETag"] = f'"{result.customer.version}"'
    response.headers["Cache-Control"] = "no-store"
    return CustomerCommandResponse.model_validate(result.to_dict())


__all__ = ["router"]

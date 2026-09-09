"""Customer creation HTTP boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.api.schemas import CustomerResponse
from erp.modules.customer.application.commands import CommandMetadata, CreateCustomer
from erp.modules.customer.application.creation import CustomerCreationService
from erp.modules.customer.domain import CustomerType, TaxIdKind
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/customers", tags=["customer-core"])


class CreateCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    customer_type: CustomerType
    identity_type: TaxIdKind
    identity_value: str = Field(min_length=1, max_length=18)
    legal_name: str = Field(min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)


class CustomerCommandResponse(BaseModel):
    customer: CustomerResponse
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False


def get_creation(request: Request) -> CustomerCreationService:
    service = getattr(request.app.state, "customer_creation", None)
    if not isinstance(service, CustomerCreationService):
        raise ApplicationError(
            code="CUSTOMER_COMMAND_UNAVAILABLE",
            message="Customer commands unavailable.",
            status_code=503,
        )
    return service


def metadata(request: Request) -> CommandMetadata:
    return CommandMetadata(
        UUID(request.state.request_id),
        UUID(request.state.correlation_id),
        request.client.host if request.client is not None else None,
    )


@router.post("", status_code=201, response_model=CustomerCommandResponse)
async def create_customer(
    body: CreateCustomerRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerCreationService, Depends(get_creation)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> CustomerCommandResponse:
    command = CreateCustomer(
        company_id=body.company_id,
        customer_type=body.customer_type,
        identity_type=body.identity_type,
        identity_value=body.identity_value,
        legal_name=body.legal_name,
        trade_name=body.trade_name,
        idempotency_key=idempotency_key,
        metadata=metadata(request),
    )
    result = await service.create(context, command)
    response.headers["Location"] = (
        f"/api/v1/customers/{result.customer.id}?company_id={result.customer.company_id}"
    )
    response.headers["ETag"] = f'"{result.customer.version}"'
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return CustomerCommandResponse.model_validate(result.to_dict())


__all__ = ["CustomerCommandResponse", "metadata", "router"]

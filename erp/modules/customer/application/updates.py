"""Authorized, versioned changes to mutable customer master data."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.commands import CommandMetadata, CustomerCommandResult
from erp.modules.customer.application.permissions import CUSTOMER_UPDATE, CustomerAuthorization
from erp.modules.customer.domain import Customer, CustomerStatus
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class UpdateCustomer:
    company_id: UUID
    customer_id: UUID
    expected_version: int
    metadata: CommandMetadata
    legal_name: str | None = None
    trade_name: str | None = None
    clear_trade_name: bool = False
    status: CustomerStatus | None = None


def apply_customer_update(customer: Customer, command: UpdateCustomer) -> Customer:
    if customer.version != command.expected_version:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The resource was changed by another transaction.",
            status_code=409,
        )
    if (
        command.legal_name is None
        and command.trade_name is None
        and not command.clear_trade_name
        and command.status is None
    ):
        raise ApplicationError(
            code="EMPTY_PATCH", message="At least one mutable field is required.", status_code=422
        )
    try:
        changed = customer.update_master(
            legal_name=customer.legal_name if command.legal_name is None else command.legal_name,
            trade_name=None
            if command.clear_trade_name
            else customer.trade_name
            if command.trade_name is None
            else command.trade_name,
        )
        if command.status is not None:
            changed = changed.transition_status(command.status)
        return changed
    except ValueError as error:
        raise ApplicationError(
            code="BUSINESS_VALIDATION_ERROR",
            message="Invalid customer data.",
            status_code=422,
            details=[ErrorDetail(message=str(error))],
        ) from error


class CustomerUpdateStore(Protocol):
    async def update(self, command: UpdateCustomer, actor_id: UUID) -> CustomerCommandResult: ...


class CustomerUpdateService:
    def __init__(self, store: CustomerUpdateStore, authorization: CustomerAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def update(
        self, context: SecurityContext, command: UpdateCustomer
    ) -> CustomerCommandResult:
        await self._authorization.require(context, command.company_id, CUSTOMER_UPDATE, write=True)
        return await self._store.update(command, context.principal.user_id)


__all__ = [
    "CustomerUpdateService",
    "CustomerUpdateStore",
    "UpdateCustomer",
    "apply_customer_update",
]

"""Authorized customer creation orchestrates one atomic persistence port."""

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.commands import (
    CreateCustomer,
    CustomerCommandResult,
    CustomerCreationStore,
)
from erp.modules.customer.application.permissions import CUSTOMER_CREATE, CustomerAuthorization
from erp.modules.customer.domain import Customer
from erp.platform.errors import ApplicationError, ErrorDetail


class CustomerCreationService:
    def __init__(self, store: CustomerCreationStore, authorization: CustomerAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreateCustomer
    ) -> CustomerCommandResult:
        await self._authorization.require(context, command.company_id, CUSTOMER_CREATE, write=True)
        try:
            customer = Customer.create(
                company_id=command.company_id,
                customer_type=command.customer_type,
                identity_type=command.identity_type,
                identity_value=command.identity_value,
                legal_name=command.legal_name,
                trade_name=command.trade_name,
            )
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid customer data.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error
        return await self._store.create(customer, command, context.principal.user_id)


__all__ = ["CustomerCreationService"]

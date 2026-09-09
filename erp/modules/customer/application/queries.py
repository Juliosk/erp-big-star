"""Paginated M14 customer queries; authorization precedes every read."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.permissions import CUSTOMER_READ, CustomerAuthorization
from erp.modules.customer.domain import Customer, CustomerStatus, CustomerType
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class CustomerPage:
    items: tuple[Customer, ...]
    page: int
    page_size: int
    has_more: bool


class CustomerDirectory(Protocol):
    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: CustomerStatus | None,
        customer_type: CustomerType | None,
    ) -> CustomerPage: ...

    async def get(self, company_id: UUID, customer_id: UUID) -> Customer | None: ...


class CustomerQueries:
    def __init__(self, directory: CustomerDirectory, authorization: CustomerAuthorization) -> None:
        self._directory = directory
        self._authorization = authorization

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: CustomerStatus | None = None,
        customer_type: CustomerType | None = None,
    ) -> CustomerPage:
        await self._authorization.require(context, company_id, CUSTOMER_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
            )
        return await self._directory.list(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            customer_type=customer_type,
        )

    async def get(self, context: SecurityContext, company_id: UUID, customer_id: UUID) -> Customer:
        await self._authorization.require(context, company_id, CUSTOMER_READ)
        customer = await self._directory.get(company_id, customer_id)
        if customer is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
            )
        return customer


__all__ = ["CustomerDirectory", "CustomerPage", "CustomerQueries"]

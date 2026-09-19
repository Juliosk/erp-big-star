"""Authorized M4 Sales Order queries."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.permissions import SALES_ORDER_READ, SalesAuthorization
from erp.modules.sales.domain import SalesOrder
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class SalesOrderPage:
    items: tuple[SalesOrder, ...]
    page: int
    page_size: int
    has_more: bool


class SalesOrderStore(Protocol):
    async def list(
        self, company_id: UUID, *, page: int, page_size: int
    ) -> SalesOrderPage: ...

    async def get(self, company_id: UUID, order_id: UUID) -> SalesOrder | None: ...


class SalesOrderService:
    def __init__(self, store: SalesOrderStore, authorization: SalesAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> SalesOrderPage:
        await self._authorization.require(context, company_id, SALES_ORDER_READ)
        if type(page) is not int or not 1 <= page <= 100_000:
            raise _validation("Invalid page.")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise _validation("Invalid page size.")
        return await self._store.list(company_id, page=page, page_size=page_size)

    async def get(
        self, context: SecurityContext, company_id: UUID, order_id: UUID
    ) -> SalesOrder:
        await self._authorization.require(context, company_id, SALES_ORDER_READ)
        order = await self._store.get(company_id, order_id)
        if order is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Sales order not found.", status_code=404
            )
        return order


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid sales order query.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = ["SalesOrderPage", "SalesOrderService", "SalesOrderStore"]

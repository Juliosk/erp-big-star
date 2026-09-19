"""Quote-to-order conversion application contract."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.application.permissions import (
    SALES_ORDER_CREATE,
    SALES_QUOTE_CONVERT,
    SalesAuthorization,
)
from erp.modules.sales.domain import SalesOrder


@dataclass(frozen=True, slots=True)
class ConvertQuoteToOrder:
    company_id: UUID
    quote_id: UUID
    order_number: str
    expected_version: int
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "quote_id": str(self.quote_id),
            "order_number": self.order_number,
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True, slots=True)
class SalesOrderConversionResult:
    order: SalesOrder
    quote_version: int
    event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool = False


class SalesOrderConversionStore(Protocol):
    async def convert(
        self, command: ConvertQuoteToOrder, actor_id: UUID
    ) -> SalesOrderConversionResult: ...


class SalesOrderConversionService:
    def __init__(
        self, store: SalesOrderConversionStore, authorization: SalesAuthorization
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def convert(
        self, context: SecurityContext, command: ConvertQuoteToOrder
    ) -> SalesOrderConversionResult:
        await self._authorization.require(
            context, command.company_id, SALES_ORDER_CREATE, write=True
        )
        await self._authorization.require(
            context, command.company_id, SALES_QUOTE_CONVERT, write=True
        )
        return await self._store.convert(command, context.principal.user_id)


__all__ = [
    "ConvertQuoteToOrder",
    "SalesOrderConversionResult",
    "SalesOrderConversionService",
    "SalesOrderConversionStore",
]

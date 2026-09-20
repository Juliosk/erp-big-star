"""Atomic cancellation contract for an order and its active M5 reservation."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.application.permissions import SALES_ORDER_CANCEL, SalesAuthorization
from erp.modules.sales.domain import SalesOrder, SalesOrderReservation


@dataclass(frozen=True, slots=True)
class CancelSalesOrder:
    company_id: UUID
    order_id: UUID
    expected_version: int
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "order_id": str(self.order_id),
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True, slots=True)
class SalesOrderCancellationResult:
    order: SalesOrder
    reservation: SalesOrderReservation
    inventory_event_id: UUID
    inventory_audit_event_id: UUID
    idempotency_replayed: bool = False


class SalesOrderCancellationStore(Protocol):
    async def cancel(
        self, command: CancelSalesOrder, actor_id: UUID
    ) -> SalesOrderCancellationResult: ...


class SalesOrderCancellationService:
    def __init__(
        self, store: SalesOrderCancellationStore, authorization: SalesAuthorization
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def cancel(
        self, context: SecurityContext, command: CancelSalesOrder
    ) -> SalesOrderCancellationResult:
        await self._authorization.require(
            context, command.company_id, SALES_ORDER_CANCEL, write=True
        )
        return await self._store.cancel(command, context.principal.user_id)


__all__ = [
    "CancelSalesOrder",
    "SalesOrderCancellationResult",
    "SalesOrderCancellationService",
    "SalesOrderCancellationStore",
]

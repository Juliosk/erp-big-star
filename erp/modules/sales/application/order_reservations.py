"""M4 application contract for atomically requesting an M5 stock hold."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.contracts import InventoryReservationKindContract
from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.application.permissions import SALES_ORDER_RESERVE, SalesAuthorization
from erp.modules.sales.domain import SalesOrderReservation


@dataclass(frozen=True, slots=True)
class ReserveSalesOrder:
    company_id: UUID
    order_id: UUID
    warehouse_id: UUID
    idempotency_key: str
    metadata: CommandMetadata
    location_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None
    reservation_kind: InventoryReservationKindContract = InventoryReservationKindContract.HARD
    expires_at: datetime | None = None

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "order_id": str(self.order_id),
            "warehouse_id": str(self.warehouse_id),
            "location_id": str(self.location_id) if self.location_id else None,
            "lot_id": str(self.lot_id) if self.lot_id else None,
            "pool_id": str(self.pool_id) if self.pool_id else None,
            "reservation_kind": self.reservation_kind,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(frozen=True, slots=True)
class SalesOrderReservationResult:
    reservation: SalesOrderReservation
    inventory_event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool = False


class SalesOrderReservationStore(Protocol):
    """Atomic transaction boundary implemented by the M4-M5 composition adapter."""

    async def reserve(
        self, command: ReserveSalesOrder, actor_id: UUID
    ) -> SalesOrderReservationResult: ...


class SalesOrderReservationService:
    def __init__(
        self, store: SalesOrderReservationStore, authorization: SalesAuthorization
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def reserve(
        self, context: SecurityContext, command: ReserveSalesOrder
    ) -> SalesOrderReservationResult:
        await self._authorization.require(
            context, command.company_id, SALES_ORDER_RESERVE, write=True
        )
        return await self._store.reserve(command, context.principal.user_id)


__all__ = [
    "ReserveSalesOrder",
    "SalesOrderReservationResult",
    "SalesOrderReservationService",
    "SalesOrderReservationStore",
]

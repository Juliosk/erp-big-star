"""Pure M4 state for the reservation requested from M5 by a sales order."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.sales.domain.order import SalesOrder, SalesOrderStatus
from erp.modules.sales.domain.support import require_uuid


class SalesOrderReservationStatus(StrEnum):
    REQUESTED = "REQUESTED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class SalesOrderReservationLine:
    order_item_id: UUID
    product_id: UUID
    quantity: Decimal
    pricing_snapshot_id: UUID | None


@dataclass(frozen=True, slots=True)
class SalesOrderReservation:
    """M4-owned projection; the physical reservation remains owned by M5."""

    id: UUID
    company_id: UUID
    order_id: UUID
    inventory_reservation_id: UUID | None
    hold_expires_at: datetime | None
    status: SalesOrderReservationStatus
    order_version: int
    lines: tuple[SalesOrderReservationLine, ...]
    version: int

    @classmethod
    def request(cls, order: SalesOrder) -> SalesOrderReservation:
        if order.status is not SalesOrderStatus.APPROVED:
            raise ValueError("only approved orders can request inventory reservation.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(order.company_id, "company_id"),
            order_id=require_uuid(order.id, "order_id"),
            inventory_reservation_id=None,
            hold_expires_at=None,
            status=SalesOrderReservationStatus.REQUESTED,
            order_version=order.version,
            lines=tuple(
                SalesOrderReservationLine(
                    order_item_id=item.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    pricing_snapshot_id=item.pricing_snapshot_id,
                )
                for item in order.items
            ),
            version=1,
        )

    def hold(
        self,
        inventory_reservation_id: UUID,
        *,
        expires_at: datetime | None = None,
    ) -> SalesOrderReservation:
        if self.status is not SalesOrderReservationStatus.REQUESTED:
            raise ValueError("only requested reservations can be held.")
        return replace(
            self,
            inventory_reservation_id=require_uuid(
                inventory_reservation_id, "inventory_reservation_id"
            ),
            hold_expires_at=expires_at,
            status=SalesOrderReservationStatus.HELD,
            version=self.version + 1,
        )

    def extend_hold(
        self, expires_at: datetime, *, now: datetime | None = None
    ) -> SalesOrderReservation:
        if self.status is not SalesOrderReservationStatus.HELD:
            raise ValueError("only held reservations can be extended.")
        instant = now or datetime.now(UTC)
        if expires_at.tzinfo is None or instant.tzinfo is None:
            raise ValueError("hold expiration must be timezone-aware.")
        if expires_at <= instant:
            raise ValueError("hold expiration must be in the future.")
        if expires_at > instant + timedelta(days=7):
            raise ValueError("hold extension cannot exceed seven days.")
        if self.hold_expires_at is not None and expires_at <= self.hold_expires_at:
            raise ValueError("hold expiration must move forward.")
        return replace(
            self,
            hold_expires_at=expires_at,
            version=self.version + 1,
        )

    def expire(self) -> SalesOrderReservation:
        if self.status is not SalesOrderReservationStatus.HELD:
            raise ValueError("only held reservations can expire.")
        return replace(
            self,
            status=SalesOrderReservationStatus.EXPIRED,
            version=self.version + 1,
        )

    def release(self) -> SalesOrderReservation:
        if self.status is not SalesOrderReservationStatus.HELD:
            raise ValueError("only held reservations can be released.")
        return replace(
            self,
            status=SalesOrderReservationStatus.RELEASED,
            version=self.version + 1,
        )

    def cancel(self) -> SalesOrderReservation:
        if self.status not in {
            SalesOrderReservationStatus.REQUESTED,
            SalesOrderReservationStatus.HELD,
        }:
            raise ValueError("only requested or held reservations can be cancelled.")
        return replace(
            self,
            status=SalesOrderReservationStatus.CANCELLED,
            version=self.version + 1,
        )


__all__ = [
    "SalesOrderReservation",
    "SalesOrderReservationLine",
    "SalesOrderReservationStatus",
]

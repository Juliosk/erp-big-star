"""Idempotent M5 verifier for reservation events published by M4."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.infrastructure.reservation_model import (
    InventoryReservationModel,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope

INVENTORY_SALES_RESERVATION_CONSUMER = "inventory.sales-reservation-consumer.v1"
SUPPORTED_SALES_RESERVATION_EVENTS = {
    "SalesOrderInventoryReserved": "ACTIVE",
    "SalesOrderReservationReleased": "RELEASED",
}


class InventorySalesReservationConsumer:
    """Verify M4/M5 agreement and receipt each sales event exactly once."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        expected_status = SUPPORTED_SALES_RESERVATION_EVENTS.get(envelope.message_type)
        if (
            expected_status is None
            or envelope.event_version != 1
            or envelope.producer_module != "sales"
            or envelope.producer_domain != "sales"
            or envelope.aggregate_type != "sales_order_reservation"
            or envelope.company_id is None
        ):
            raise ValueError("Unsupported sales reservation event envelope.")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            reservation_id = _inventory_reservation_id(message)
            model = await session.scalar(
                select(InventoryReservationModel).where(
                    InventoryReservationModel.company_id == message.company_id,
                    InventoryReservationModel.id == reservation_id,
                )
            )
            if model is None:
                raise ValueError("M5 inventory reservation was not found.")
            if model.reference_type != "SALES_ORDER":
                raise ValueError("M5 reservation is not owned by a sales order.")
            if model.status != expected_status:
                raise ValueError("M4 event conflicts with the M5 reservation status.")

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=INVENTORY_SALES_RESERVATION_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


def _inventory_reservation_id(message: MessageEnvelope) -> UUID:
    value = message.payload.get("inventory_reservation_id")
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Sales reservation event requires an inventory_reservation_id."
        ) from error


__all__ = [
    "INVENTORY_SALES_RESERVATION_CONSUMER",
    "SUPPORTED_SALES_RESERVATION_EVENTS",
    "InventorySalesReservationConsumer",
]

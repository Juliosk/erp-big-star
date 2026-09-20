"""Idempotent M4 projection of M5 reservation expiration events."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.domain import SalesOrderReservationStatus
from erp.modules.sales.infrastructure.order_reservation_repository import (
    SalesOrderReservationRepository,
)
from erp.modules.sales.infrastructure.reservation_effects import (
    SalesOrderReservationEffects,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope

SALES_RESERVATION_PROJECTOR = "sales.order-reservation-projector.v1"
INVENTORY_RESERVATION_EXPIRED = "InventoryReservationExpired"


class SalesOrderReservationProjectionConsumer:
    """Synchronize an M5 expiration into M4 exactly once."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        if (
            envelope.message_type != INVENTORY_RESERVATION_EXPIRED
            or envelope.event_version != 1
            or envelope.producer_module != "inventory"
            or envelope.producer_domain != "inventory"
            or envelope.aggregate_type != "inventory_reservation"
            or envelope.company_id is None
        ):
            raise ValueError("Unsupported inventory reservation event envelope.")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            order_id = _uuid_payload(message, "reference_id")
            inventory_reservation_id = _uuid_payload(message, "id")
            actor_id = _uuid_payload(message, "created_by")
            repository = SalesOrderReservationRepository(
                session, company_id=message.company_id  # type: ignore[arg-type]
            )
            current = await repository.get_for_order_update(order_id)
            if current is None:
                raise ValueError("M4 order reservation projection was not found.")
            if current.inventory_reservation_id != inventory_reservation_id:
                raise ValueError("M5 reservation does not match the M4 projection.")
            if current.status is SalesOrderReservationStatus.EXPIRED:
                return
            expired = current.expire()
            await repository.save(expired, actor_id=actor_id)
            await SalesOrderReservationEffects().record(
                session,
                expired,
                event_type="SalesOrderReservationExpired",
                actor_id=actor_id,
                metadata=CommandMetadata(
                    request_id=message.request_id,
                    correlation_id=message.correlation_id,
                    source_ip=None,
                ),
                before=current,
            )

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=SALES_RESERVATION_PROJECTOR,
                envelope=envelope,
                effect=effect,
            )


def _uuid_payload(message: MessageEnvelope, name: str) -> UUID:
    value = message.payload.get(name)
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Reservation event requires a valid {name}.") from error


__all__ = [
    "INVENTORY_RESERVATION_EXPIRED",
    "SALES_RESERVATION_PROJECTOR",
    "SalesOrderReservationProjectionConsumer",
]

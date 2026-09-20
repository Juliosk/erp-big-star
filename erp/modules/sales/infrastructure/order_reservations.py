"""Atomic M4-to-M5 order reservation transaction adapter."""

from uuid import UUID

from erp.modules.inventory.contracts import (
    OrderReservationLineContract,
    ReserveOrderInventoryContract,
)
from erp.modules.inventory.infrastructure import SessionOrderInventoryReservationGateway
from erp.modules.sales.application.order_reservations import (
    ReserveSalesOrder,
    SalesOrderReservationResult,
    SalesOrderReservationStore,
)
from erp.modules.sales.domain import SalesOrderReservation
from erp.modules.sales.infrastructure.order_repository import SalesOrderRepository
from erp.modules.sales.infrastructure.order_reservation_repository import (
    SalesOrderReservationRepository,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyService


class PostgresSalesOrderReservations(SalesOrderReservationStore):
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def reserve(
        self, command: ReserveSalesOrder, actor_id: UUID
    ) -> SalesOrderReservationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"sales:{command.company_id}:{actor_id}",
                operation="sales.order.reserve",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            projection_repository = SalesOrderReservationRepository(
                session, company_id=command.company_id
            )
            if decision.replayed:
                body = decision.response_body or {}
                projection = await projection_repository.get_for_order(command.order_id)
                if projection is None:
                    raise RuntimeError("Idempotent order reservation replay target is missing.")
                return SalesOrderReservationResult(
                    reservation=projection,
                    inventory_event_id=UUID(str(body["inventory_event_id"])),
                    audit_event_id=UUID(str(body["audit_event_id"])),
                    idempotency_replayed=True,
                )

            order = await SalesOrderRepository(
                session, company_id=command.company_id
            ).get_for_update(command.order_id)
            if order is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Sales order not found.",
                    status_code=404,
                )
            if order.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            if await projection_repository.get_for_order(order.id) is not None:
                raise _conflict("The order already has an inventory reservation.")
            try:
                requested = SalesOrderReservation.request(order)
            except ValueError as error:
                raise _validation(str(error)) from error

            inventory_result = await SessionOrderInventoryReservationGateway(
                session
            ).reserve_order(
                ReserveOrderInventoryContract(
                    company_id=command.company_id,
                    order_id=order.id,
                    lines=tuple(
                        OrderReservationLineContract(
                            product_id=line.product_id,
                            quantity=line.quantity,
                            warehouse_id=command.warehouse_id,
                            location_id=command.location_id,
                            lot_id=command.lot_id,
                            pool_id=command.pool_id,
                        )
                        for line in requested.lines
                    ),
                    idempotency_key=command.idempotency_key,
                    request_id=command.metadata.request_id,
                    correlation_id=command.metadata.correlation_id,
                    source_ip=command.metadata.source_ip,
                    reservation_kind=command.reservation_kind,
                    expires_at=command.expires_at,
                ),
                actor_id,
            )
            held = requested.hold(inventory_result.reservation.id)
            await projection_repository.add(held, actor_id=actor_id)
            response_body: dict[str, object] = {
                "order_id": str(order.id),
                "reservation_id": str(held.id),
                "inventory_reservation_id": str(inventory_result.reservation.id),
                "inventory_event_id": str(inventory_result.event_id),
                "audit_event_id": str(inventory_result.audit_event_id),
            }
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=response_body
            )
            return SalesOrderReservationResult(
                held, inventory_result.event_id, inventory_result.audit_event_id
            )


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Sales order cannot be reserved.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


def _conflict(message: str) -> ApplicationError:
    return ApplicationError(
        code="SALES_ORDER_RESERVATION_CONFLICT",
        message="Sales order reservation conflict.",
        status_code=409,
        details=[ErrorDetail(message=message)],
    )


__all__ = ["PostgresSalesOrderReservations"]

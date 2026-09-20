"""Single transaction for Sales Order cancellation and M5 hold release."""

from uuid import UUID

from erp.modules.inventory.contracts import ReleaseOrderInventoryContract
from erp.modules.inventory.infrastructure import SessionOrderInventoryReservationGateway
from erp.modules.sales.application.order_cancellation import (
    CancelSalesOrder,
    SalesOrderCancellationResult,
    SalesOrderCancellationStore,
)
from erp.modules.sales.infrastructure.order_repository import SalesOrderRepository
from erp.modules.sales.infrastructure.order_reservation_repository import (
    SalesOrderReservationRepository,
)
from erp.modules.sales.infrastructure.reservation_effects import (
    SalesOrderReservationEffects,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyService


class PostgresSalesOrderCancellation(SalesOrderCancellationStore):
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def cancel(
        self, command: CancelSalesOrder, actor_id: UUID
    ) -> SalesOrderCancellationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"sales:{command.company_id}:{actor_id}",
                operation="sales.order.cancel",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            orders = SalesOrderRepository(session, company_id=command.company_id)
            reservations = SalesOrderReservationRepository(
                session, company_id=command.company_id
            )
            if decision.replayed:
                body = decision.response_body or {}
                order = await orders.get(command.order_id)
                reservation = await reservations.get_for_order(command.order_id)
                if order is None or reservation is None:
                    raise RuntimeError("Idempotent cancellation replay target is missing.")
                return SalesOrderCancellationResult(
                    order,
                    reservation,
                    UUID(str(body["inventory_event_id"])),
                    UUID(str(body["inventory_audit_event_id"])),
                    True,
                )
            order = await orders.get_for_update(command.order_id)
            if order is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Sales order not found.",
                    status_code=404,
                )
            if order.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            reservation = await reservations.get_for_order_update(command.order_id)
            if reservation is None or reservation.inventory_reservation_id is None:
                raise _conflict("The order has no active inventory reservation.")
            try:
                cancelled_order = order.cancel()
                released_projection = reservation.release()
            except ValueError as error:
                raise _validation(str(error)) from error
            inventory_result = await SessionOrderInventoryReservationGateway(
                session
            ).release_order(
                ReleaseOrderInventoryContract(
                    company_id=command.company_id,
                    reservation_id=reservation.inventory_reservation_id,
                    request_id=command.metadata.request_id,
                    correlation_id=command.metadata.correlation_id,
                    source_ip=command.metadata.source_ip,
                ),
                actor_id,
            )
            await reservations.save(released_projection, actor_id=actor_id)
            await orders.save(cancelled_order, actor_id=actor_id)
            await SalesOrderReservationEffects().record(
                session,
                released_projection,
                event_type="SalesOrderReservationReleased",
                actor_id=actor_id,
                metadata=command.metadata,
                before=reservation,
            )
            response_body: dict[str, object] = {
                "order_id": str(order.id),
                "reservation_id": str(reservation.id),
                "inventory_event_id": str(inventory_result.event_id),
                "inventory_audit_event_id": str(inventory_result.audit_event_id),
            }
            await self._idempotency.complete(
                session, decision, response_status=200, response_body=response_body
            )
            return SalesOrderCancellationResult(
                cancelled_order,
                released_projection,
                inventory_result.event_id,
                inventory_result.audit_event_id,
            )


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Sales order cannot be cancelled.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


def _conflict(message: str) -> ApplicationError:
    return ApplicationError(
        code="SALES_ORDER_RESERVATION_CONFLICT",
        message="Sales order cancellation conflict.",
        status_code=409,
        details=[ErrorDetail(message=message)],
    )


__all__ = ["PostgresSalesOrderCancellation"]

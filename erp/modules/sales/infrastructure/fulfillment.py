"""PostgreSQL transaction boundary for Sales/WMS fulfillment."""

from uuid import UUID

from erp.modules.sales.application.fulfillment import (
    FulfillSalesOrder,
    SalesFulfillmentCandidate,
    SalesFulfillmentResult,
    SalesFulfillmentStore,
)
from erp.modules.sales.domain import (
    ChannelOrderStatus,
    SalesShipment,
    ShippingLabel,
)
from erp.modules.sales.infrastructure.channel_repository import (
    MultichannelSalesOrderRepository,
    SalesChannelConfigRepository,
)
from erp.modules.sales.infrastructure.fulfillment_effects import (
    SalesFulfillmentEffects,
)
from erp.modules.sales.infrastructure.fulfillment_repository import (
    SalesShipmentRepository,
)
from erp.modules.wms.infrastructure.fulfillment_gateway import (
    SessionOutboundShipmentGateway,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresSalesFulfillment(SalesFulfillmentStore):
    def __init__(self, database: Database, *, ttl_seconds: int = 86_400) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def get_candidate(
        self, company_id: UUID, order_id: UUID
    ) -> SalesFulfillmentCandidate | None:
        async with self._database.session() as session:
            order = await MultichannelSalesOrderRepository(
                session, company_id=company_id
            ).get(order_id)
            if order is None:
                return None
            account = await SalesChannelConfigRepository(
                session, company_id=company_id
            ).get(order.channel_config_id)
            if account is None or not account.active:
                return None
            reference = order.snapshot.reference
            return SalesFulfillmentCandidate(
                company_id=company_id,
                order_id=order.id,
                channel_config_id=order.channel_config_id,
                account_id=reference.account_id,
                marketplace=reference.marketplace,
                external_order_id=reference.external_order_id,
                order_status=order.snapshot.status,
                order_version=order.record_version,
                credential_reference=account.credential_reference,
            )

    async def fulfill(
        self,
        command: FulfillSalesOrder,
        label: ShippingLabel,
        actor_id: UUID,
    ) -> SalesFulfillmentResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"sales-fulfillment:{command.company_id}:{actor_id}",
                operation="sales.fulfillment.dispatch",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored sales fulfillment has no response body.")
                return SalesFulfillmentResult.replay(decision.response_body)

            orders = MultichannelSalesOrderRepository(
                session, company_id=command.company_id
            )
            order = await orders.get_for_update(command.order_id)
            if order is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Multichannel sales order not found.",
                    status_code=404,
                )
            if order.record_version != command.expected_order_version:
                raise OptimisticLockError(
                    expected_version=command.expected_order_version
                )
            if order.snapshot.status is not ChannelOrderStatus.PAID:
                raise ApplicationError(
                    code="SALES_FULFILLMENT_CONFLICT",
                    message="Only paid orders can be fulfilled.",
                    status_code=409,
                )
            dispatched_wms = await SessionOutboundShipmentGateway(session).dispatch(
                company_id=command.company_id,
                shipment_id=command.wms_shipment_id,
                expected_version=command.expected_wms_version,
                carrier_code=label.carrier_code,
                tracking_code=label.tracking_code,
                actor_id=actor_id,
            )
            shipped_order = order.revise(
                order.snapshot.transition(ChannelOrderStatus.SHIPPED)
            )
            await orders.save(
                shipped_order,
                actor_id=actor_id,
                expected_version=command.expected_order_version,
            )
            reference = order.snapshot.reference
            labeled_shipment = SalesShipment.create(
                company_id=command.company_id,
                sales_order_id=order.id,
                wms_shipment_id=command.wms_shipment_id,
                channel_config_id=order.channel_config_id,
                account_id=reference.account_id,
                marketplace=reference.marketplace,
                external_order_id=reference.external_order_id,
                label=label,
            )
            shipment_repository = SalesShipmentRepository(
                session, company_id=command.company_id
            )
            await shipment_repository.add(labeled_shipment, actor_id=actor_id)
            shipment = await shipment_repository.dispatch(
                labeled_shipment.id,
                dispatched_at=dispatched_wms.dispatched_at,
                actor_id=actor_id,
                command=command,
            )
            event_id, audit_id = await SalesFulfillmentEffects().record(
                session,
                command,
                shipment,
                dispatched_wms,
                actor_id=actor_id,
            )
            result = SalesFulfillmentResult(
                shipment=shipment,
                order_status=shipped_order.snapshot.status,
                order_version=shipped_order.record_version,
                wms_shipment=dispatched_wms,
                event_id=event_id,
                audit_event_id=audit_id,
            )
            await self._idempotency.complete(
                session,
                decision,
                response_status=201,
                response_body=result.to_dict(),
            )
            return result


__all__ = ["PostgresSalesFulfillment"]

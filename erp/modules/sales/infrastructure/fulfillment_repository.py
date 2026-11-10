"""Tenant-bound repository for multichannel shipment and append-only history."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.application.fulfillment import FulfillSalesOrder
from erp.modules.sales.domain import (
    Marketplace,
    SalesShipment,
    SalesShipmentStatus,
    ShippingLabel,
)
from erp.modules.sales.infrastructure.fulfillment_model import (
    SalesFulfillmentLogModel,
    SalesShipmentModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


class SalesShipmentRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        self._session = session
        self._company_id = company_id

    async def add(
        self,
        shipment: SalesShipment,
        *,
        actor_id: UUID,
    ) -> SalesShipment:
        if shipment.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="Sales shipment is outside the selected company.",
                status_code=403,
            )
        if (
            shipment.status is not SalesShipmentStatus.LABEL_CREATED
            or shipment.version != 1
        ):
            raise ValueError("A new sales shipment must start labeled at version one.")
        label = shipment.label
        self._session.add(
            SalesShipmentModel(
                id=shipment.id,
                company_id=self._company_id,
                sales_order_id=shipment.sales_order_id,
                wms_shipment_id=shipment.wms_shipment_id,
                channel_config_id=shipment.channel_config_id,
                account_id=shipment.account_id,
                marketplace=shipment.marketplace,
                external_order_id=shipment.external_order_id,
                status=shipment.status,
                carrier_code=label.carrier_code,
                service_code=label.service_code,
                tracking_code=label.tracking_code,
                label_reference=label.label_reference,
                dispatched_at=shipment.dispatched_at,
                version=shipment.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise ApplicationError(
                    code="SALES_FULFILLMENT_CONFLICT",
                    message="Sales shipment conflicts with existing fulfillment data.",
                    status_code=409,
                ) from error
            raise
        return shipment

    async def dispatch(
        self,
        shipment_id: UUID,
        *,
        dispatched_at: datetime,
        actor_id: UUID,
        command: FulfillSalesOrder,
    ) -> SalesShipment:
        model = await self._session.scalar(
            select(SalesShipmentModel)
            .where(
                SalesShipmentModel.company_id == self._company_id,
                SalesShipmentModel.id == shipment_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if model is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Sales shipment not found.",
                status_code=404,
            )
        if model.version != 1:
            raise OptimisticLockError(expected_version=1)
        labeled = _shipment(model)
        dispatched = labeled.dispatch(now=dispatched_at)
        model.status = dispatched.status
        model.dispatched_at = dispatched.dispatched_at
        model.updated_by = actor_id
        await self._session.flush()
        persisted = _shipment(model)
        await self._append_logs(persisted, actor_id=actor_id, command=command)
        return persisted

    async def get(self, shipment_id: UUID) -> SalesShipment | None:
        model = await self._session.scalar(
            select(SalesShipmentModel).where(
                SalesShipmentModel.company_id == self._company_id,
                SalesShipmentModel.id == shipment_id,
            )
        )
        return None if model is None else _shipment(model)

    async def get_by_order(self, order_id: UUID) -> SalesShipment | None:
        model = await self._session.scalar(
            select(SalesShipmentModel).where(
                SalesShipmentModel.company_id == self._company_id,
                SalesShipmentModel.sales_order_id == order_id,
            )
        )
        return None if model is None else _shipment(model)

    async def list_logs(
        self, shipment_id: UUID
    ) -> tuple[SalesFulfillmentLogModel, ...]:
        return tuple(
            await self._session.scalars(
                select(SalesFulfillmentLogModel)
                .where(
                    SalesFulfillmentLogModel.company_id == self._company_id,
                    SalesFulfillmentLogModel.shipment_id == shipment_id,
                )
                .order_by(SalesFulfillmentLogModel.sequence)
            )
        )

    async def _append_logs(
        self,
        shipment: SalesShipment,
        *,
        actor_id: UUID,
        command: FulfillSalesOrder,
    ) -> None:
        payload = {
            "sales_order_id": str(shipment.sales_order_id),
            "wms_shipment_id": str(shipment.wms_shipment_id),
            "tracking_code": shipment.label.tracking_code,
            "carrier_code": shipment.label.carrier_code,
        }
        events: Sequence[str] = (
            "SEPARATION_CONFIRMED",
            "LABEL_CREATED",
            "DISPATCHED",
            "CHANNEL_SYNC_REQUESTED",
        )
        for sequence, event_type in enumerate(events, start=1):
            self._session.add(
                SalesFulfillmentLogModel(
                    id=uuid4(),
                    company_id=self._company_id,
                    shipment_id=shipment.id,
                    sequence=sequence,
                    event_type=event_type,
                    payload=payload,
                    actor_id=actor_id,
                    request_id=command.metadata.request_id,
                    correlation_id=command.metadata.correlation_id,
                )
            )
        await self._session.flush()


def _shipment(model: SalesShipmentModel) -> SalesShipment:
    return SalesShipment(
        id=model.id,
        company_id=model.company_id,
        sales_order_id=model.sales_order_id,
        wms_shipment_id=model.wms_shipment_id,
        channel_config_id=model.channel_config_id,
        account_id=model.account_id,
        marketplace=Marketplace(model.marketplace),
        external_order_id=model.external_order_id,
        status=SalesShipmentStatus(model.status),
        label=ShippingLabel(
            carrier_code=model.carrier_code,
            service_code=model.service_code,
            tracking_code=model.tracking_code,
            label_reference=model.label_reference,
        ),
        dispatched_at=model.dispatched_at,
        version=model.version,
    )


__all__ = ["SalesShipmentRepository", "_shipment"]

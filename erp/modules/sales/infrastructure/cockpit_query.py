"""PostgreSQL read model for the multichannel Sales cockpit."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select

from erp.modules.sales.application.cockpit import (
    SalesChannelPulse,
    SalesCockpitCostProvider,
    SalesCockpitOrder,
    SalesCockpitSnapshot,
)
from erp.modules.sales.domain import Marketplace
from erp.modules.sales.infrastructure.channel_model import ChannelSalesOrderModel
from erp.modules.sales.infrastructure.fulfillment_model import SalesShipmentModel
from erp.platform.database import Database

_CENT = Decimal("0.01")


class PostgresSalesCockpitReader:
    def __init__(self, database: Database, costs: SalesCockpitCostProvider) -> None:
        self._database = database
        self._costs = costs

    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> SalesCockpitSnapshot:
        async with self._database.session() as session:
            orders = list(
                (
                    await session.scalars(
                        select(ChannelSalesOrderModel)
                        .where(ChannelSalesOrderModel.company_id == company_id)
                        .order_by(
                            ChannelSalesOrderModel.updated_at.desc(),
                            ChannelSalesOrderModel.id,
                        )
                        .limit(limit)
                    )
                ).all()
            )
            order_ids = [order.id for order in orders]
            shipments = (
                list(
                    (
                        await session.scalars(
                            select(SalesShipmentModel).where(
                                SalesShipmentModel.company_id == company_id,
                                SalesShipmentModel.sales_order_id.in_(order_ids),
                            )
                        )
                    ).all()
                )
                if order_ids
                else []
            )

        product_ids = frozenset(
            UUID(str(item["product_id"]))
            for order in orders
            for item in order.items
        )
        costs = await self._costs.standard_costs(company_id, product_ids)
        shipment_by_order = {shipment.sales_order_id: shipment for shipment in shipments}
        cockpit_orders: list[SalesCockpitOrder] = []
        grouped: defaultdict[str, list[SalesCockpitOrder]] = defaultdict(list)
        for order in orders:
            margin_amount, margin_percent = _margin(order, costs)
            shipment = shipment_by_order.get(order.id)
            reconciliation_status = (
                "CHANNEL_SYNC_PENDING"
                if order.status == "SHIPPED"
                and (shipment is None or shipment.status != "DISPATCHED")
                else "RECONCILED"
            )
            value = SalesCockpitOrder(
                id=order.id,
                external_order_id=order.external_order_id,
                marketplace=order.marketplace,
                status=order.status,
                reconciliation_status=reconciliation_status,
                total_amount=order.total_amount,
                margin_amount=margin_amount,
                margin_percent=margin_percent,
                shipment_status=None if shipment is None else shipment.status,
                tracking_code=None if shipment is None else shipment.tracking_code,
                updated_at=order.updated_at,
            )
            cockpit_orders.append(value)
            grouped[order.marketplace].append(value)

        channels = tuple(
            _channel_pulse(marketplace.value, grouped[marketplace.value])
            for marketplace in Marketplace
        )
        return SalesCockpitSnapshot(
            company_id=company_id,
            generated_at=as_of,
            channels=channels,
            orders=tuple(cockpit_orders),
            reconciled_orders=sum(
                order.reconciliation_status == "RECONCILED" for order in cockpit_orders
            ),
            margin_pending_orders=sum(order.margin_amount is None for order in cockpit_orders),
        )


def _margin(
    order: ChannelSalesOrderModel,
    costs: dict[UUID, Decimal],
) -> tuple[Decimal | None, Decimal | None]:
    total_cost = Decimal("0")
    for item in order.items:
        product_id = UUID(str(item["product_id"]))
        unit_cost = costs.get(product_id)
        if unit_cost is None:
            return None, None
        total_cost += unit_cost * Decimal(str(item["quantity"]))
    margin = (order.total_amount - total_cost).quantize(_CENT, rounding=ROUND_HALF_UP)
    if order.total_amount == 0:
        return margin, None
    percent = (margin / order.total_amount * Decimal("100")).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    return margin, percent


def _channel_pulse(marketplace: str, orders: list[SalesCockpitOrder]) -> SalesChannelPulse:
    complete_margins = [order.margin_amount for order in orders if order.margin_amount is not None]
    pending = sum(order.margin_amount is None for order in orders)
    sales_amount = sum((order.total_amount for order in orders), Decimal("0"))
    margin_amount = None if pending else sum(complete_margins, Decimal("0"))
    margin_percent = (
        None
        if margin_amount is None or sales_amount == 0
        else (margin_amount / sales_amount * Decimal("100")).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
    )
    return SalesChannelPulse(
        marketplace=marketplace,
        order_count=len(orders),
        pending_count=sum(order.status == "PENDING" for order in orders),
        paid_count=sum(order.status == "PAID" for order in orders),
        shipped_count=sum(order.status == "SHIPPED" for order in orders),
        cancelled_count=sum(order.status == "CANCELLED" for order in orders),
        sales_amount=sales_amount,
        margin_amount=margin_amount,
        margin_percent=margin_percent,
        margin_pending_orders=pending,
    )


__all__ = ["PostgresSalesCockpitReader"]

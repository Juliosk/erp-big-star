"""Tenant-bound M4 Sales Order repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.domain import SalesOrder, SalesOrderItem, SalesOrderStatus
from erp.modules.sales.infrastructure.order_model import SalesOrderItemModel, SalesOrderModel
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _order(model: SalesOrderModel, items: tuple[SalesOrderItemModel, ...]) -> SalesOrder:
    return SalesOrder(
        id=model.id,
        company_id=model.company_id,
        number=model.number,
        source_quote_id=model.source_quote_id,
        source_quote_revision_number=model.source_quote_revision_number,
        customer_id=model.customer_id,
        seller_id=model.seller_id,
        currency=model.currency,
        status=SalesOrderStatus(model.status),
        items=tuple(
            SalesOrderItem(
                id=item.id,
                company_id=item.company_id,
                order_id=item.order_id,
                quote_revision_item_id=item.quote_revision_item_id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=item.discount_amount,
                pricing_snapshot_id=item.pricing_snapshot_id,
            )
            for item in items
        ),
        gross_amount=model.gross_amount,
        discount_amount=model.discount_amount,
        net_amount=model.net_amount,
        version=model.version,
    )


class SalesOrderRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        self._session = session
        self._company_id = company_id

    async def add(self, order: SalesOrder, *, actor_id: UUID) -> None:
        if order.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN", message="Order outside selected company.", status_code=403
            )
        self._session.add(
            SalesOrderModel(
                id=order.id,
                company_id=order.company_id,
                number=order.number,
                source_quote_id=order.source_quote_id,
                source_quote_revision_number=order.source_quote_revision_number,
                customer_id=order.customer_id,
                seller_id=order.seller_id,
                currency=order.currency,
                status=order.status,
                gross_amount=order.gross_amount,
                discount_amount=order.discount_amount,
                net_amount=order.net_amount,
                version=order.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush()
        for item in order.items:
            self._session.add(
                SalesOrderItemModel(
                    id=item.id,
                    company_id=item.company_id,
                    order_id=item.order_id,
                    quote_revision_item_id=item.quote_revision_item_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount_amount=item.discount_amount,
                    pricing_snapshot_id=item.pricing_snapshot_id,
                    created_by=actor_id,
                )
            )
        await self._flush()

    async def get(self, order_id: UUID) -> SalesOrder | None:
        models = await self._session.scalars(
            select(SalesOrderModel).where(
                SalesOrderModel.company_id == self._company_id,
                SalesOrderModel.id == order_id,
            )
        )
        model = models.one_or_none()
        return None if model is None else await self._hydrate(model)

    async def get_for_update(self, order_id: UUID) -> SalesOrder | None:
        model = await self._session.scalar(
            select(SalesOrderModel)
            .where(
                SalesOrderModel.company_id == self._company_id,
                SalesOrderModel.id == order_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return None if model is None else await self._hydrate(model)

    async def list(self, *, limit: int, offset: int) -> tuple[SalesOrder, ...]:
        models = await self._session.scalars(
            select(SalesOrderModel)
            .where(SalesOrderModel.company_id == self._company_id)
            .order_by(SalesOrderModel.number, SalesOrderModel.id)
            .limit(limit)
            .offset(offset)
        )
        return tuple([await self._hydrate(model) for model in models])

    async def save(self, order: SalesOrder, *, actor_id: UUID) -> SalesOrder:
        if order.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN", message="Order outside selected company.", status_code=403
            )
        model = await self._session.scalar(
            select(SalesOrderModel)
            .where(
                SalesOrderModel.company_id == self._company_id,
                SalesOrderModel.id == order.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if model is None or model.version != order.version - 1:
            raise OptimisticLockError(expected_version=order.version - 1)
        model.status = order.status
        model.updated_by = actor_id
        await self._session.flush()
        return order

    async def _hydrate(self, model: SalesOrderModel) -> SalesOrder:
        items = await self._session.scalars(
            select(SalesOrderItemModel)
            .where(
                SalesOrderItemModel.company_id == self._company_id,
                SalesOrderItemModel.order_id == model.id,
            )
            .order_by(SalesOrderItemModel.id)
        )
        return _order(model, tuple(items))

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="SALES_ORDER_CONFLICT",
                    message="An order already exists for this number or quote.",
                    status_code=409,
                ) from error
            raise


__all__ = ["SalesOrderRepository"]

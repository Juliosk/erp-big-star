"""Append-only PostgreSQL repository for shop-floor evidence."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.application.shop_floor import (
    ScrapEntry,
    ShopFloorExecutionLogStore,
    ShopFloorOperationLog,
)
from erp.modules.production.domain import ProductionConflictError, ProductionScopeError
from erp.modules.production.infrastructure.shop_floor_model import (
    ScrapRecordModel,
    ShopFloorOperationLogModel,
)


class ShopFloorExecutionRepository(ShopFloorExecutionLogStore):
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def append(
        self,
        log: ShopFloorOperationLog,
        scraps: tuple[ScrapEntry, ...],
    ) -> None:
        if log.company_id != self._company_id:
            raise ProductionScopeError("shop-floor log belongs to another company.")
        self._session.add(
            ShopFloorOperationLogModel(
                id=log.id,
                company_id=log.company_id,
                production_order_id=log.production_order_id,
                operation_sequence=log.operation_sequence,
                event_type=log.event_type.value,
                work_center_code=log.work_center_code,
                good_quantity=log.good_quantity,
                material_consumptions=[
                    {"product_id": str(value.product_id), "quantity": str(value.quantity)}
                    for value in log.material_consumptions
                ],
                occurred_at=log.occurred_at,
                actor_id=log.actor_id,
                order_version_before=log.order_version_before,
                order_version_after=log.order_version_after,
                request_id=log.request_id,
                correlation_id=log.correlation_id,
            )
        )
        try:
            await self._session.flush()
            self._session.add_all(
                [
                    ScrapRecordModel(
                        id=uuid4(),
                        company_id=log.company_id,
                        operation_log_id=log.id,
                        production_order_id=log.production_order_id,
                        operation_sequence=log.operation_sequence,
                        product_id=value.product_id,
                        quantity=value.quantity,
                        reason_code=value.reason_code,
                        notes=value.notes,
                        occurred_at=log.occurred_at,
                        actor_id=log.actor_id,
                    )
                    for value in scraps
                ]
            )
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise ProductionConflictError(
                    "Shop-floor evidence conflicts with the order, route or request."
                ) from error
            raise

    async def totals(
        self,
        production_order_id: UUID,
        operation_sequence: int,
    ) -> tuple[Decimal, Decimal]:
        good = await self._session.scalar(
            select(func.coalesce(func.sum(ShopFloorOperationLogModel.good_quantity), 0)).where(
                ShopFloorOperationLogModel.company_id == self._company_id,
                ShopFloorOperationLogModel.production_order_id == production_order_id,
                ShopFloorOperationLogModel.operation_sequence == operation_sequence,
            )
        )
        scrap = await self._session.scalar(
            select(func.coalesce(func.sum(ScrapRecordModel.quantity), 0)).where(
                ScrapRecordModel.company_id == self._company_id,
                ScrapRecordModel.production_order_id == production_order_id,
                ScrapRecordModel.operation_sequence == operation_sequence,
            )
        )
        return Decimal(good or 0), Decimal(scrap or 0)


__all__ = ["ShopFloorExecutionRepository"]

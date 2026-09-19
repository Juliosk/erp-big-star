"""Tenant-bound persistence for the M4 view of an M5 stock hold."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.domain import (
    SalesOrderReservation,
    SalesOrderReservationLine,
    SalesOrderReservationStatus,
)
from erp.modules.sales.infrastructure.order_reservation_model import (
    SalesOrderReservationLineModel,
    SalesOrderReservationModel,
)
from erp.platform.errors import ApplicationError


class SalesOrderReservationRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        self._session = session
        self._company_id = company_id

    async def add(self, reservation: SalesOrderReservation, *, actor_id: UUID) -> None:
        self._assert_company(reservation.company_id)
        self._session.add(
            SalesOrderReservationModel(
                id=reservation.id,
                company_id=reservation.company_id,
                order_id=reservation.order_id,
                inventory_reservation_id=reservation.inventory_reservation_id,
                status=reservation.status,
                order_version=reservation.order_version,
                version=reservation.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        for line in reservation.lines:
            self._session.add(
                SalesOrderReservationLineModel(
                    id=line.order_item_id,
                    company_id=reservation.company_id,
                    reservation_id=reservation.id,
                    order_item_id=line.order_item_id,
                    product_id=line.product_id,
                    quantity=line.quantity,
                    pricing_snapshot_id=line.pricing_snapshot_id,
                    created_by=actor_id,
                )
            )
        await self._session.flush()

    async def get_for_order(self, order_id: UUID) -> SalesOrderReservation | None:
        model = await self._session.scalar(
            select(SalesOrderReservationModel).where(
                SalesOrderReservationModel.company_id == self._company_id,
                SalesOrderReservationModel.order_id == order_id,
            )
        )
        if model is None:
            return None
        rows = await self._session.scalars(
            select(SalesOrderReservationLineModel)
            .where(
                SalesOrderReservationLineModel.company_id == self._company_id,
                SalesOrderReservationLineModel.reservation_id == model.id,
            )
            .order_by(SalesOrderReservationLineModel.order_item_id)
        )
        return _reservation(model, tuple(rows))

    def _assert_company(self, company_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="Order reservation outside selected company.",
                status_code=403,
            )


def _reservation(
    model: SalesOrderReservationModel,
    lines: tuple[SalesOrderReservationLineModel, ...],
) -> SalesOrderReservation:
    return SalesOrderReservation(
        id=model.id,
        company_id=model.company_id,
        order_id=model.order_id,
        inventory_reservation_id=model.inventory_reservation_id,
        status=SalesOrderReservationStatus(model.status),
        order_version=model.order_version,
        version=model.version,
        lines=tuple(
            SalesOrderReservationLine(
                order_item_id=line.order_item_id,
                product_id=line.product_id,
                quantity=line.quantity,
                pricing_snapshot_id=line.pricing_snapshot_id,
            )
            for line in lines
        ),
    )


__all__ = ["SalesOrderReservationRepository"]

"""PostgreSQL reservation and availability adapters for M5."""

from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from erp.modules.inventory.application.queries import InventoryPage
from erp.modules.inventory.application.reservations import (
    InventoryAvailabilityDirectory,
    InventoryReservationStore,
)
from erp.modules.inventory.domain import (
    InventoryAvailability,
    InventoryBalance,
    InventoryReservation,
    InventoryReservationAllocation,
    InventoryReservationKind,
    InventoryReservationStatus,
    InventoryState,
    Quantity,
)
from erp.modules.inventory.infrastructure.balance_model import InventoryBalanceModel
from erp.modules.inventory.infrastructure.balance_repository import _balance
from erp.modules.inventory.infrastructure.reservation_model import (
    InventoryReservationAllocationModel,
    InventoryReservationModel,
)
from erp.platform.database import Database


class PostgresInventoryReservations(
    InventoryReservationStore, InventoryAvailabilityDirectory
):
    """Session-owning reservation adapter with explicit company scope."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def add(self, reservation: InventoryReservation) -> InventoryReservation:
        async with self._database.session() as session, session.begin():
            model = _reservation_model(reservation)
            session.add(model)
        return reservation

    async def get(
        self, company_id: UUID, reservation_id: UUID
    ) -> InventoryReservation | None:
        async with self._database.session() as session:
            model = await session.scalar(
                select(InventoryReservationModel)
                .options(selectinload(InventoryReservationModel.allocations))
                .where(
                    InventoryReservationModel.company_id == company_id,
                    InventoryReservationModel.id == reservation_id,
                )
            )
            return None if model is None else _reservation(model)

    async def list_reservations(
        self,
        company_id: UUID,
        *,
        status: InventoryReservationStatus | None,
        reservation_kind: InventoryReservationKind | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryReservation]:
        async with self._database.session() as session:
            offset = (page - 1) * page_size
            statement = (
                select(InventoryReservationModel)
                .options(selectinload(InventoryReservationModel.allocations))
                .where(InventoryReservationModel.company_id == company_id)
            )
            statement = _reservation_filters(
                statement, status=status, reservation_kind=reservation_kind
            )
            statement = statement.order_by(
                InventoryReservationModel.created_at.desc(),
                InventoryReservationModel.id,
            )
            models = (
                await session.scalars(statement.limit(page_size).offset(offset))
            ).all()
            more = (
                await session.scalars(statement.limit(1).offset(offset + page_size))
            ).first()
            return InventoryPage(tuple(_reservation(model) for model in models), page, page_size, bool(more))

    async def list_availability(
        self,
        company_id: UUID,
        *,
        product_id: UUID | None,
        warehouse_id: UUID | None,
        lot_id: UUID | None,
        state: InventoryState | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryAvailability]:
        async with self._database.session() as session:
            offset = (page - 1) * page_size
            statement = select(InventoryBalanceModel).where(
                InventoryBalanceModel.company_id == company_id
            )
            if product_id is not None:
                statement = statement.where(InventoryBalanceModel.product_id == product_id)
            if warehouse_id is not None:
                statement = statement.where(InventoryBalanceModel.warehouse_id == warehouse_id)
            if lot_id is not None:
                statement = statement.where(InventoryBalanceModel.lot_id == lot_id)
            if state is not None:
                statement = statement.where(InventoryBalanceModel.state == state)
            statement = statement.order_by(
                InventoryBalanceModel.product_id,
                InventoryBalanceModel.warehouse_id,
                InventoryBalanceModel.id,
            )
            balances = (
                await session.scalars(statement.limit(page_size).offset(offset))
            ).all()
            more = (
                await session.scalars(statement.limit(1).offset(offset + page_size))
            ).first()
            reserved = {
                balance.id: await _reserved_for_balance(session, _balance(balance))
                for balance in balances
            }
            items = tuple(
                InventoryAvailability.calculate(
                    company_id=balance.company_id,
                    product_id=balance.product_id,
                    warehouse_id=balance.warehouse_id,
                    location_id=balance.location_id,
                    lot_id=balance.lot_id,
                    pool_id=balance.pool_id,
                    state=InventoryState(balance.state),
                    on_hand=Quantity(balance.quantity),
                    hard_reserved=Quantity(reserved[balance.id][InventoryReservationKind.HARD]),
                    soft_reserved=Quantity(reserved[balance.id][InventoryReservationKind.SOFT]),
                    version=balance.version,
                )
                for balance in balances
            )
            return InventoryPage(items, page, page_size, bool(more))


def _reservation_filters(
    statement: Any,
    *,
    status: InventoryReservationStatus | None,
    reservation_kind: InventoryReservationKind | None,
) -> Any:
    if status is not None:
        statement = statement.where(InventoryReservationModel.status == status)
    if reservation_kind is not None:
        statement = statement.where(InventoryReservationModel.reservation_kind == reservation_kind)
    return statement


async def _reserved_for_balance(session: Any, balance: InventoryBalance) -> dict[InventoryReservationKind, Decimal]:
    statement = (
        select(
            InventoryReservationModel.reservation_kind,
            func.coalesce(func.sum(InventoryReservationAllocationModel.quantity), Decimal("0")),
        )
        .join(
            InventoryReservationAllocationModel,
            (InventoryReservationAllocationModel.company_id == InventoryReservationModel.company_id)
            & (
                InventoryReservationAllocationModel.reservation_id
                == InventoryReservationModel.id
            ),
        )
        .where(
            InventoryReservationModel.company_id == balance.company_id,
            InventoryReservationModel.status == InventoryReservationStatus.ACTIVE,
            InventoryReservationAllocationModel.product_id == balance.product_id,
            InventoryReservationAllocationModel.warehouse_id == balance.warehouse_id,
            InventoryReservationAllocationModel.state == balance.state,
        )
        .group_by(InventoryReservationModel.reservation_kind)
    )
    statement = _optional_dimension(
        statement, InventoryReservationAllocationModel.location_id, balance.location_id
    )
    statement = _optional_dimension(
        statement, InventoryReservationAllocationModel.lot_id, balance.lot_id
    )
    statement = _optional_dimension(
        statement, InventoryReservationAllocationModel.pool_id, balance.pool_id
    )
    rows = await session.execute(statement)
    values = {
        InventoryReservationKind.HARD: Decimal("0"),
        InventoryReservationKind.SOFT: Decimal("0"),
    }
    for kind, quantity in rows:
        values[InventoryReservationKind(kind)] = quantity or Decimal("0")
    return values


def _optional_dimension(statement: Any, column: Any, value: UUID | None) -> Any:
    return statement.where(column.is_(None) if value is None else column == value)


def _reservation_model(reservation: InventoryReservation) -> InventoryReservationModel:
    return InventoryReservationModel(
        id=reservation.id,
        company_id=reservation.company_id,
        reservation_kind=reservation.reservation_kind,
        status=reservation.status,
        reference_type=reservation.reference_type,
        reference_id=reservation.reference_id,
        expires_at=reservation.expires_at,
        created_at=reservation.created_at,
        created_by=reservation.created_by,
        version=reservation.version,
        allocations=[
            _allocation_model(allocation)
            for allocation in reservation.allocations
        ],
    )


def _allocation_model(
    allocation: InventoryReservationAllocation,
) -> InventoryReservationAllocationModel:
    return InventoryReservationAllocationModel(
        id=allocation.id,
        reservation_id=allocation.reservation_id,
        company_id=allocation.company_id,
        product_id=allocation.product_id,
        warehouse_id=allocation.warehouse_id,
        location_id=allocation.location_id,
        lot_id=allocation.lot_id,
        pool_id=allocation.pool_id,
        state=allocation.state,
        quantity=allocation.quantity.value,
    )


def _reservation(model: InventoryReservationModel) -> InventoryReservation:
    return InventoryReservation(
        id=model.id,
        company_id=model.company_id,
        reservation_kind=InventoryReservationKind(model.reservation_kind),
        status=InventoryReservationStatus(model.status),
        reference_type=model.reference_type,
        reference_id=model.reference_id,
        expires_at=model.expires_at,
        created_at=model.created_at,
        created_by=model.created_by,
        version=model.version,
        allocations=tuple(_allocation(item) for item in _ordered(model.allocations)),
    )


def _ordered(
    allocations: Iterable[InventoryReservationAllocationModel],
) -> tuple[InventoryReservationAllocationModel, ...]:
    return tuple(sorted(allocations, key=lambda item: str(item.id)))


def _allocation(model: InventoryReservationAllocationModel) -> InventoryReservationAllocation:
    return InventoryReservationAllocation(
        id=model.id,
        reservation_id=model.reservation_id,
        company_id=model.company_id,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        location_id=model.location_id,
        lot_id=model.lot_id,
        pool_id=model.pool_id,
        state=InventoryState(model.state),
        quantity=Quantity(model.quantity),
    )


__all__ = ["PostgresInventoryReservations"]

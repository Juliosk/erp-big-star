"""PostgreSQL reservation and availability adapters for M5."""

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, NamedTuple, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from erp.modules.inventory.application.commands import (
    CreateInventoryReservation,
    InventoryReservationLine,
    InventoryReservationResult,
    ReleaseInventoryReservation,
)
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
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyService


class StockBucket(NamedTuple):
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: InventoryState


class PostgresInventoryReservations(
    InventoryReservationStore, InventoryAvailabilityDirectory
):
    """Session-owning reservation adapter with explicit company scope."""

    def __init__(self, database: Database, *, ttl_seconds: int | None = None) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds or 86_400)

    async def add(self, reservation: InventoryReservation) -> InventoryReservation:
        async with self._database.session() as session, session.begin():
            model = _reservation_model(reservation)
            session.add(model)
        return reservation

    async def reserve(
        self, command: CreateInventoryReservation, actor_id: UUID
    ) -> InventoryReservationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"inventory:{command.company_id}:{actor_id}",
                operation="inventory.reservation.reserve",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored inventory reservation replay has no response body.")
                return InventoryReservationResult.replay(decision.response_body)
            if command.reservation_kind is InventoryReservationKind.HARD:
                await _assert_hard_availability(session, command)
            reservation = _reservation_from_command(command, actor_id=actor_id)
            session.add(_reservation_model(reservation))
            try:
                await session.flush()
            except IntegrityError as error:
                if getattr(error.orig, "sqlstate", None) == "23505":
                    raise _reservation_conflict(
                        "An active or historical reservation already exists for this reference."
                    ) from error
                raise
            result = InventoryReservationResult(reservation)
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=result.to_dict()
            )
            return result

    async def release(
        self, command: ReleaseInventoryReservation, actor_id: UUID
    ) -> InventoryReservationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"inventory:{command.company_id}:{actor_id}",
                operation="inventory.reservation.release",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored inventory reservation release replay has no body.")
                return InventoryReservationResult.replay(decision.response_body)
            model = await session.scalar(
                select(InventoryReservationModel)
                .options(selectinload(InventoryReservationModel.allocations))
                .where(
                    InventoryReservationModel.company_id == command.company_id,
                    InventoryReservationModel.id == command.reservation_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if model is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Inventory reservation not found.",
                    status_code=404,
                )
            if model.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            try:
                _reservation(model).release()
            except ValueError as error:
                raise _reservation_conflict(str(error)) from error
            model.status = InventoryReservationStatus.RELEASED
            await session.flush()
            result = InventoryReservationResult(_reservation(model))
            await self._idempotency.complete(
                session, decision, response_status=200, response_body=result.to_dict()
            )
            return result

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


async def _assert_hard_availability(session: Any, command: CreateInventoryReservation) -> None:
    requested = _requested_by_bucket(command.lines)
    for bucket, quantity in requested.items():
        balance = await _locked_balance(session, command.company_id, bucket)
        if balance is None:
            raise _reservation_conflict("No available balance exists for the requested stock bucket.")
        reserved = await _active_hard_reserved(session, command.company_id, bucket)
        available = balance.quantity - reserved
        if available < quantity:
            raise _reservation_conflict(
                "Requested HARD reservation exceeds available inventory.",
            )


def _requested_by_bucket(
    lines: tuple[InventoryReservationLine, ...],
) -> dict[StockBucket, Decimal]:
    result: dict[StockBucket, Decimal] = {}
    for line in lines:
        bucket = StockBucket(
            product_id=line.product_id,
            warehouse_id=line.warehouse_id,
            location_id=line.location_id,
            lot_id=line.lot_id,
            pool_id=line.pool_id,
            state=InventoryState(line.state),
        )
        result[bucket] = result.get(bucket, Decimal("0")) + line.quantity
    return result


async def _locked_balance(
    session: Any, company_id: UUID, bucket: StockBucket
) -> InventoryBalanceModel | None:
    statement = select(InventoryBalanceModel).where(
        InventoryBalanceModel.company_id == company_id,
        InventoryBalanceModel.product_id == bucket.product_id,
        InventoryBalanceModel.warehouse_id == bucket.warehouse_id,
        InventoryBalanceModel.state == bucket.state,
    )
    statement = _optional_dimension(statement, InventoryBalanceModel.location_id, bucket.location_id)
    statement = _optional_dimension(statement, InventoryBalanceModel.lot_id, bucket.lot_id)
    statement = _optional_dimension(statement, InventoryBalanceModel.pool_id, bucket.pool_id)
    return cast(
        InventoryBalanceModel | None,
        await session.scalar(
            statement.with_for_update().execution_options(populate_existing=True)
        ),
    )


async def _active_hard_reserved(session: Any, company_id: UUID, bucket: StockBucket) -> Decimal:
    statement = (
        select(func.coalesce(func.sum(InventoryReservationAllocationModel.quantity), Decimal("0")))
        .join(
            InventoryReservationModel,
            (InventoryReservationModel.company_id == InventoryReservationAllocationModel.company_id)
            & (
                InventoryReservationModel.id
                == InventoryReservationAllocationModel.reservation_id
            ),
        )
        .where(
            InventoryReservationModel.company_id == company_id,
            InventoryReservationModel.status == InventoryReservationStatus.ACTIVE,
            InventoryReservationModel.reservation_kind == InventoryReservationKind.HARD,
            InventoryReservationAllocationModel.product_id == bucket.product_id,
            InventoryReservationAllocationModel.warehouse_id == bucket.warehouse_id,
            InventoryReservationAllocationModel.state == bucket.state,
        )
    )
    statement = _optional_dimension(
        statement, InventoryReservationAllocationModel.location_id, bucket.location_id
    )
    statement = _optional_dimension(statement, InventoryReservationAllocationModel.lot_id, bucket.lot_id)
    statement = _optional_dimension(statement, InventoryReservationAllocationModel.pool_id, bucket.pool_id)
    value = await session.scalar(statement)
    return value or Decimal("0")


def _reservation_from_command(
    command: CreateInventoryReservation, *, actor_id: UUID
) -> InventoryReservation:
    reservation_id = uuid4()
    return InventoryReservation.create(
        company_id=command.company_id,
        reservation_kind=command.reservation_kind,
        reference_type=command.reference_type,
        reference_id=command.reference_id,
        created_by=actor_id,
        expires_at=command.expires_at,
        allocations=tuple(
            line.allocation(reservation_id=reservation_id, company_id=command.company_id)
            for line in command.lines
        ),
    )


def _reservation_conflict(message: str) -> ApplicationError:
    return ApplicationError(
        code="INVENTORY_RESERVATION_CONFLICT",
        message="Inventory reservation cannot be completed.",
        status_code=409,
        details=[ErrorDetail(message=message)],
    )


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

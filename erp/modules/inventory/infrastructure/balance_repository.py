"""Transactional PostgreSQL balance repository for M5."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.domain import (
    InventoryBalance,
    InventoryPosting,
    InventoryState,
    Quantity,
)
from erp.modules.inventory.infrastructure.balance_model import InventoryBalanceModel
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError, ErrorDetail


class InventoryBalanceRepository:
    """Update one company-scoped balance dimension with SQLAlchemy versioning."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def apply(self, posting: InventoryPosting) -> InventoryBalance:
        if posting.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The inventory posting is outside the selected company.",
                status_code=403,
            )
        model = await self._find_model_for_update(posting)
        if model is None:
            balance = _balance_from_posting(posting)
            model = _model(balance)
            self._session.add(model)
            try:
                await self._session.flush()
            except IntegrityError as error:
                if getattr(error.orig, "sqlstate", None) == "23505":
                    raise OptimisticLockError(expected_version=1) from error
                raise
            return _balance(model)
        balance = _apply_quantity(_balance(model), posting)
        model.quantity = balance.quantity.value
        await self._session.flush()
        return _balance(model)

    async def get_for_posting(self, posting: InventoryPosting) -> InventoryBalance | None:
        model = await self._find_model(posting, for_update=False)
        return None if model is None else _balance(model)

    async def list(
        self,
        *,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        lot_id: UUID | None = None,
        state: InventoryState | None = None,
        limit: int,
        offset: int,
    ) -> tuple[InventoryBalance, ...]:
        statement = select(InventoryBalanceModel).where(
            InventoryBalanceModel.company_id == self._company_id
        )
        if product_id is not None:
            statement = statement.where(InventoryBalanceModel.product_id == product_id)
        if warehouse_id is not None:
            statement = statement.where(InventoryBalanceModel.warehouse_id == warehouse_id)
        if lot_id is not None:
            statement = statement.where(InventoryBalanceModel.lot_id == lot_id)
        if state is not None:
            statement = statement.where(InventoryBalanceModel.state == state)
        result = await self._session.scalars(
            statement.order_by(
                InventoryBalanceModel.product_id,
                InventoryBalanceModel.warehouse_id,
                InventoryBalanceModel.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(_balance(model) for model in result)

    async def save(self, balance: InventoryBalance, *, expected_version: int) -> InventoryBalance:
        if balance.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The inventory balance is outside the selected company.",
                status_code=403,
            )
        model = await self._session.scalar(
            select(InventoryBalanceModel)
            .where(
                InventoryBalanceModel.company_id == self._company_id,
                InventoryBalanceModel.id == balance.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if model is None or model.company_id != self._company_id:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Inventory balance not found.", status_code=404
            )
        if model.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        model.quantity = balance.quantity.value
        await self._session.flush()
        return _balance(model)

    async def _find_model_for_update(
        self, posting: InventoryPosting
    ) -> InventoryBalanceModel | None:
        return await self._find_model(posting, for_update=True)

    async def _find_model(
        self, posting: InventoryPosting, *, for_update: bool
    ) -> InventoryBalanceModel | None:
        statement = select(InventoryBalanceModel).where(
            InventoryBalanceModel.company_id == self._company_id,
            InventoryBalanceModel.product_id == posting.product_id,
            InventoryBalanceModel.warehouse_id == posting.warehouse_id,
            InventoryBalanceModel.state == posting.state,
        )
        statement = _optional_dimension(
            statement, InventoryBalanceModel.location_id, posting.location_id
        )
        statement = _optional_dimension(statement, InventoryBalanceModel.lot_id, posting.lot_id)
        statement = _optional_dimension(statement, InventoryBalanceModel.pool_id, posting.pool_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement.execution_options(populate_existing=True))
        return result.one_or_none()


def _optional_dimension(statement: Any, column: Any, value: UUID | None) -> Any:
    return statement.where(column.is_(None) if value is None else column == value)


def _model(balance: InventoryBalance) -> InventoryBalanceModel:
    return InventoryBalanceModel(
        id=balance.id,
        company_id=balance.company_id,
        product_id=balance.product_id,
        warehouse_id=balance.warehouse_id,
        location_id=balance.location_id,
        lot_id=balance.lot_id,
        pool_id=balance.pool_id,
        state=balance.state,
        quantity=balance.quantity.value,
        version=balance.version,
    )


def _balance_from_posting(posting: InventoryPosting) -> InventoryBalance:
    try:
        return InventoryBalance.from_posting(posting)
    except ValueError as error:
        raise _negative_balance_error() from error


def _apply_quantity(balance: InventoryBalance, posting: InventoryPosting) -> InventoryBalance:
    try:
        return balance.apply(posting.quantity_delta)
    except ValueError as error:
        raise _negative_balance_error() from error


def _negative_balance_error() -> ApplicationError:
    return ApplicationError(
        code="INVENTORY_NEGATIVE_BALANCE",
        message="Inventory balance cannot become negative.",
        status_code=409,
        details=[ErrorDetail(message="The requested stock adjustment would create negative stock.")],
    )


def _balance(model: InventoryBalanceModel) -> InventoryBalance:
    return InventoryBalance(
        id=model.id,
        company_id=model.company_id,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        location_id=model.location_id,
        lot_id=model.lot_id,
        pool_id=model.pool_id,
        state=InventoryState(model.state),
        quantity=Quantity(model.quantity),
        version=model.version,
    )


__all__ = ["InventoryBalanceRepository", "_balance"]

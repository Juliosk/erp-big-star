"""Authorized inventory adjustment command service."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.application.commands import (
    CreateInventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentResult,
    InventoryAdjustmentType,
)
from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.application.permissions import (
    INVENTORY_ADJUSTMENT_CREATE,
    InventoryAuthorization,
)
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
)
from erp.platform.errors import ApplicationError, ErrorDetail


class InventoryAdjustmentStore(Protocol):
    async def adjust(
        self, command: CreateInventoryAdjustment, actor_id: UUID
    ) -> InventoryAdjustmentResult: ...


class InventoryAdjustmentService:
    """Authorize and convert adjustment commands into immutable ledger entries."""

    def __init__(
        self, store: InventoryAdjustmentStore, authorization: InventoryAuthorization
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def adjust(
        self, context: SecurityContext, command: CreateInventoryAdjustment
    ) -> InventoryAdjustmentResult:
        await self._authorization.require(
            context, command.company_id, INVENTORY_ADJUSTMENT_CREATE, write=True
        )
        _validate_command(command)
        try:
            return await self._store.adjust(command, context.principal.user_id)
        except ValueError as error:
            raise _validation(str(error)) from error


def build_adjustment_entry(
    command: CreateInventoryAdjustment,
    *,
    actor_id: UUID,
    current_quantities: Sequence[Decimal] | None = None,
) -> InventoryLedgerEntry:
    if current_quantities is not None and len(current_quantities) != len(command.lines):
        raise ValueError("current quantity vector must match adjustment lines.")
    transaction = InventoryTransaction.create(
        company_id=command.company_id,
        transaction_type=InventoryTransactionType.ADJUSTMENT,
        reference_type=f"{command.adjustment_type.value}_ADJUSTMENT",
        created_by=actor_id,
    )
    postings = tuple(
        InventoryPosting.create(
            company_id=command.company_id,
            transaction_id=transaction.id,
            sequence=index,
            product_id=line.product_id,
            warehouse_id=line.warehouse_id,
            location_id=line.location_id,
            lot_id=line.lot_id,
            pool_id=line.pool_id,
            state=InventoryState(line.state),
            quantity_delta=_signed_quantity(
                command.adjustment_type,
                line.quantity,
                current_quantities[index - 1] if current_quantities is not None else Decimal("0"),
            ),
        )
        for index, line in enumerate(command.lines, start=1)
    )
    return InventoryLedgerEntry(transaction, postings)


def _signed_quantity(
    adjustment_type: InventoryAdjustmentType, value: Decimal, current_quantity: Decimal
) -> Decimal:
    if adjustment_type is InventoryAdjustmentType.OUTBOUND:
        return -abs(value)
    if adjustment_type is InventoryAdjustmentType.BALANCE:
        delta = value - current_quantity
        if delta == Decimal("0"):
            raise ValueError("balance adjustment does not change current quantity.")
        return delta
    return value


def _validate_command(command: CreateInventoryAdjustment) -> None:
    if not command.lines:
        raise _validation("At least one adjustment line is required.")
    reason = command.reason.strip()
    if not 3 <= len(reason) <= 500:
        raise _validation("reason must contain 3 to 500 trimmed characters.")
    for line in command.lines:
        _validate_line(command.adjustment_type, line)


def _validate_line(adjustment_type: InventoryAdjustmentType, line: InventoryAdjustmentLine) -> None:
    if adjustment_type is InventoryAdjustmentType.BALANCE:
        if line.quantity < Decimal("0"):
            raise _validation("balance adjustment target cannot be negative.")
    elif line.quantity <= Decimal("0"):
        raise _validation("adjustment quantity must be positive.")
    try:
        InventoryState(line.state)
    except ValueError as error:
        raise _validation("state must be an official inventory state.") from error


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid inventory adjustment.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "InventoryAdjustmentService",
    "InventoryAdjustmentStore",
    "build_adjustment_entry",
]

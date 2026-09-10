"""Immutable inventory ledger facts."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.inventory.domain.stock import InventoryState


class InventoryTransactionType(StrEnum):
    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"


def _signed_quantity(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError("quantity delta must be represented as Decimal.")
    if not value.is_finite():
        raise ValueError("quantity delta must be finite.")
    if value == Decimal("0"):
        raise ValueError("quantity delta cannot be zero.")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -6:
        raise ValueError("quantity delta supports at most six decimal places.")
    return value


def _occurred_at(value: datetime | None) -> datetime:
    candidate = value or datetime.now(UTC)
    if not isinstance(candidate, datetime):
        raise ValueError("occurred_at must be a datetime.")
    if candidate.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware.")
    return candidate


def _reference_type(value: str) -> str:
    candidate = value.strip().upper()
    if not 2 <= len(candidate) <= 64 or not candidate.replace("_", "").isalnum():
        raise ValueError("reference_type must contain 2 to 64 canonical characters.")
    return candidate


@dataclass(frozen=True, slots=True)
class InventoryTransaction:
    id: UUID
    company_id: UUID
    transaction_type: InventoryTransactionType
    reference_type: str
    reference_id: UUID | None
    occurred_at: datetime
    created_by: UUID

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.company_id, self.created_by)
        ):
            raise ValueError("Transaction identity, company and actor must be UUIDs.")
        if not isinstance(self.transaction_type, InventoryTransactionType):
            raise ValueError("transaction_type must be an official inventory type.")
        object.__setattr__(self, "reference_type", _reference_type(self.reference_type))
        if self.reference_id is not None and not isinstance(self.reference_id, UUID):
            raise ValueError("reference_id must be a UUID when present.")
        object.__setattr__(self, "occurred_at", _occurred_at(self.occurred_at))

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        transaction_type: InventoryTransactionType,
        reference_type: str,
        created_by: UUID,
        reference_id: UUID | None = None,
        occurred_at: datetime | None = None,
    ) -> InventoryTransaction:
        return cls(
            id=uuid4(),
            company_id=company_id,
            transaction_type=transaction_type,
            reference_type=reference_type,
            reference_id=reference_id,
            occurred_at=_occurred_at(occurred_at),
            created_by=created_by,
        )


@dataclass(frozen=True, slots=True)
class InventoryPosting:
    id: UUID
    company_id: UUID
    transaction_id: UUID
    sequence: int
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: InventoryState
    quantity_delta: Decimal

    def __post_init__(self) -> None:
        required = (
            self.id,
            self.company_id,
            self.transaction_id,
            self.product_id,
            self.warehouse_id,
        )
        if not all(isinstance(value, UUID) for value in required):
            raise ValueError(
                "Posting identity, company, transaction, product and warehouse must be UUIDs."
            )
        for optional in (self.location_id, self.lot_id, self.pool_id):
            if optional is not None and not isinstance(optional, UUID):
                raise ValueError("Optional posting dimensions must be UUIDs when present.")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("sequence must be a positive integer.")
        if not isinstance(self.state, InventoryState):
            raise ValueError("state must be an official inventory state.")
        object.__setattr__(self, "quantity_delta", _signed_quantity(self.quantity_delta))

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        transaction_id: UUID,
        sequence: int,
        product_id: UUID,
        warehouse_id: UUID,
        quantity_delta: Decimal,
        state: InventoryState = InventoryState.AVAILABLE,
        location_id: UUID | None = None,
        lot_id: UUID | None = None,
        pool_id: UUID | None = None,
    ) -> InventoryPosting:
        return cls(
            id=uuid4(),
            company_id=company_id,
            transaction_id=transaction_id,
            sequence=sequence,
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=location_id,
            lot_id=lot_id,
            pool_id=pool_id,
            state=state,
            quantity_delta=quantity_delta,
        )


__all__ = [
    "InventoryPosting",
    "InventoryTransaction",
    "InventoryTransactionType",
]

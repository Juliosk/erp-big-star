"""Durable company-scoped stock balances derived from ledger postings."""

from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

from erp.modules.inventory.domain.ledger import InventoryPosting
from erp.modules.inventory.domain.stock import InventoryState, Quantity


@dataclass(frozen=True, slots=True)
class InventoryBalance:
    id: UUID
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: InventoryState
    quantity: Quantity
    version: int

    def __post_init__(self) -> None:
        required = (self.id, self.company_id, self.product_id, self.warehouse_id)
        if not all(isinstance(value, UUID) for value in required):
            raise ValueError("Balance identity, company, product and warehouse must be UUIDs.")
        for optional in (self.location_id, self.lot_id, self.pool_id):
            if optional is not None and not isinstance(optional, UUID):
                raise ValueError("Optional balance dimensions must be UUIDs when present.")
        if not isinstance(self.state, InventoryState):
            raise ValueError("state must be an official inventory state.")
        if not isinstance(self.quantity, Quantity):
            raise ValueError("quantity must be an inventory Quantity.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def empty_from_posting(cls, posting: InventoryPosting) -> InventoryBalance:
        return cls(
            id=uuid4(),
            company_id=posting.company_id,
            product_id=posting.product_id,
            warehouse_id=posting.warehouse_id,
            location_id=posting.location_id,
            lot_id=posting.lot_id,
            pool_id=posting.pool_id,
            state=posting.state,
            quantity=Quantity.of("0"),
            version=1,
        )

    @classmethod
    def from_posting(cls, posting: InventoryPosting) -> InventoryBalance:
        if posting.quantity_delta < Decimal("0"):
            raise ValueError("inventory balance cannot become negative.")
        return cls(
            id=uuid4(),
            company_id=posting.company_id,
            product_id=posting.product_id,
            warehouse_id=posting.warehouse_id,
            location_id=posting.location_id,
            lot_id=posting.lot_id,
            pool_id=posting.pool_id,
            state=posting.state,
            quantity=Quantity(posting.quantity_delta),
            version=1,
        )

    def apply(self, quantity_delta: Decimal) -> InventoryBalance:
        candidate = self.quantity.value + quantity_delta
        if candidate < Decimal("0"):
            raise ValueError("inventory balance cannot become negative.")
        changed = replace(self, quantity=Quantity(candidate))
        if changed == self:
            return self
        return replace(changed, version=self.version + 1)


__all__ = ["InventoryBalance"]

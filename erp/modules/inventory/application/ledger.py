"""Technology-neutral ports for immutable inventory ledger writes."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.inventory.domain import InventoryPosting, InventoryTransaction


@dataclass(frozen=True, slots=True)
class InventoryLedgerEntry:
    transaction: InventoryTransaction
    postings: tuple[InventoryPosting, ...]

    def __post_init__(self) -> None:
        if not self.postings:
            raise ValueError("Ledger entry must contain at least one posting.")
        sequences = tuple(posting.sequence for posting in self.postings)
        if sequences != tuple(range(1, len(self.postings) + 1)):
            raise ValueError("Ledger postings must have contiguous one-based sequences.")
        for posting in self.postings:
            if posting.company_id != self.transaction.company_id:
                raise ValueError("Ledger posting company must match transaction company.")
            if posting.transaction_id != self.transaction.id:
                raise ValueError("Ledger posting transaction must match the header.")

    @property
    def company_id(self) -> UUID:
        return self.transaction.company_id


__all__ = ["InventoryLedgerEntry"]

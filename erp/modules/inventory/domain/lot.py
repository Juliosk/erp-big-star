"""Product lot identity for inventory movements."""

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4


class InventoryLotStatus(StrEnum):
    OPEN = "OPEN"
    QUARANTINED = "QUARANTINED"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class InventoryLot:
    id: UUID
    company_id: UUID
    product_id: UUID
    code: str
    status: InventoryLotStatus
    expires_on: date | None
    version: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.company_id, self.product_id)
        ):
            raise ValueError("Lot identity, company and product must be UUIDs.")
        normalized_code = self.code.strip().upper()
        if re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{1,63}", normalized_code) is None:
            raise ValueError("code must contain 2 to 64 canonical lot characters.")
        object.__setattr__(self, "code", normalized_code)
        if not isinstance(self.status, InventoryLotStatus):
            raise ValueError("status must be an official inventory lot status.")
        if self.expires_on is not None and not isinstance(self.expires_on, date):
            raise ValueError("expires_on must be a date when present.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls, *, company_id: UUID, product_id: UUID, code: str, expires_on: date | None = None
    ) -> InventoryLot:
        return cls(
            id=uuid4(),
            company_id=company_id,
            product_id=product_id,
            code=code,
            status=InventoryLotStatus.OPEN,
            expires_on=expires_on,
            version=1,
        )


__all__ = ["InventoryLot", "InventoryLotStatus"]

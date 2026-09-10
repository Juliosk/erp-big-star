"""Inventory pools separate stock purpose without leaving M5."""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


class InventoryPoolKind(StrEnum):
    MARKETPLACE = "MARKETPLACE"
    B2B = "B2B"
    STORE = "STORE"


@dataclass(frozen=True, slots=True)
class InventoryPool:
    id: UUID
    company_id: UUID
    code: str
    name: str
    kind: InventoryPoolKind
    active: bool
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise ValueError("Pool identity and company scope must be UUIDs.")
        normalized_code = self.code.strip().upper()
        if re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,49}", normalized_code) is None:
            raise ValueError("code must contain 2 to 50 canonical characters.")
        object.__setattr__(self, "code", normalized_code)
        normalized_name = self.name.strip()
        if not 1 <= len(normalized_name) <= 120:
            raise ValueError("name must contain 1 to 120 trimmed characters.")
        object.__setattr__(self, "name", normalized_name)
        if not isinstance(self.kind, InventoryPoolKind):
            raise ValueError("kind must be an official inventory pool kind.")
        if type(self.active) is not bool:
            raise ValueError("active must be a boolean.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls, *, company_id: UUID, code: str, name: str, kind: InventoryPoolKind
    ) -> InventoryPool:
        return cls(
            id=uuid4(),
            company_id=company_id,
            code=code,
            name=name,
            kind=kind,
            active=True,
            version=1,
        )


__all__ = ["InventoryPool", "InventoryPoolKind"]

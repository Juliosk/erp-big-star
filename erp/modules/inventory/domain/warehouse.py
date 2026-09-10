"""Warehouse and location structure owned by M5."""

import re
from dataclasses import dataclass, replace
from uuid import UUID, uuid4


def _code(value: str, *, field: str, maximum: int = 50) -> str:
    normalized = value.strip().upper()
    if (
        not 2 <= len(normalized) <= maximum
        or re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", normalized) is None
    ):
        raise ValueError(f"{field} must contain 2 to {maximum} canonical characters.")
    return normalized


def _name(value: str, *, field: str = "name", maximum: int = 120) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= maximum:
        raise ValueError(f"{field} must contain 1 to {maximum} trimmed characters.")
    return normalized


@dataclass(frozen=True, slots=True)
class Warehouse:
    id: UUID
    company_id: UUID
    branch_id: UUID
    code: str
    name: str
    active: bool
    version: int

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (self.id, self.company_id, self.branch_id)):
            raise ValueError("Warehouse identity, company and branch must be UUIDs.")
        object.__setattr__(self, "code", _code(self.code, field="code"))
        object.__setattr__(self, "name", _name(self.name))
        if type(self.active) is not bool:
            raise ValueError("active must be a boolean.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(cls, *, company_id: UUID, branch_id: UUID, code: str, name: str) -> Warehouse:
        return cls(
            id=uuid4(),
            company_id=company_id,
            branch_id=branch_id,
            code=code,
            name=name,
            active=True,
            version=1,
        )

    def rename(self, name: str) -> Warehouse:
        candidate = replace(self, name=name)
        if candidate == self:
            return self
        return replace(candidate, version=self.version + 1)

    def deactivate(self) -> Warehouse:
        if not self.active:
            return self
        return replace(self, active=False, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class WarehouseLocation:
    id: UUID
    company_id: UUID
    warehouse_id: UUID
    code: str
    name: str
    parent_location_id: UUID | None
    active: bool
    version: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.company_id, self.warehouse_id)
        ):
            raise ValueError("Location identity, company and warehouse must be UUIDs.")
        if self.parent_location_id is not None and not isinstance(self.parent_location_id, UUID):
            raise ValueError("parent location must be a UUID when present.")
        if self.parent_location_id == self.id:
            raise ValueError("Location cannot be its own parent.")
        object.__setattr__(self, "code", _code(self.code, field="code"))
        object.__setattr__(self, "name", _name(self.name))
        if type(self.active) is not bool:
            raise ValueError("active must be a boolean.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        warehouse_id: UUID,
        code: str,
        name: str,
        parent_location_id: UUID | None = None,
    ) -> WarehouseLocation:
        return cls(
            id=uuid4(),
            company_id=company_id,
            warehouse_id=warehouse_id,
            code=code,
            name=name,
            parent_location_id=parent_location_id,
            active=True,
            version=1,
        )


__all__ = ["Warehouse", "WarehouseLocation"]

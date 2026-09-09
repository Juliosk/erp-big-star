"""Customer groups and memberships owned by the M14 boundary."""

import re
from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class CustomerGroup:
    id: UUID
    company_id: UUID
    code: str
    name: str
    description: str | None
    active: bool
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise ValueError("Group identity and company scope must be UUIDs.")
        if re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,49}", self.code) is None:
            raise ValueError("code must contain 2 to 50 uppercase letters, digits, '_' or '-'.")
        _trimmed(self.name, field="name", minimum=1, maximum=120)
        if self.description is not None:
            _trimmed(self.description, field="description", minimum=1, maximum=500)
        if type(self.active) is not bool:
            raise ValueError("active must be a boolean.")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        name: str,
        description: str | None = None,
        active: bool = True,
    ) -> CustomerGroup:
        return cls(
            id=uuid4(),
            company_id=company_id,
            code=code.strip().upper(),
            name=name.strip(),
            description=description.strip() if description is not None else None,
            active=active,
            version=1,
        )


@dataclass(frozen=True, slots=True)
class CustomerGroupMember:
    id: UUID
    company_id: UUID
    customer_id: UUID
    customer_group_id: UUID

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (self.id, self.company_id, self.customer_id, self.customer_group_id)
        ):
            raise ValueError("Membership identity, company, customer and group must be UUIDs.")

    @classmethod
    def assign(
        cls, *, company_id: UUID, customer_id: UUID, customer_group_id: UUID
    ) -> CustomerGroupMember:
        return cls(
            id=uuid4(),
            company_id=company_id,
            customer_id=customer_id,
            customer_group_id=customer_group_id,
        )


def _trimmed(value: str, *, field: str, minimum: int, maximum: int) -> None:
    if not minimum <= len(value) <= maximum or value != value.strip():
        raise ValueError(f"{field} must contain {minimum} to {maximum} trimmed characters.")


__all__ = ["CustomerGroup", "CustomerGroupMember"]

"""Customer contacts owned by the M14 aggregate boundary."""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


class CustomerContactRole(StrEnum):
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    COMMERCIAL = "COMMERCIAL"
    FISCAL = "FISCAL"


class CustomerContactKind(StrEnum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"


@dataclass(frozen=True, slots=True)
class CustomerContact:
    id: UUID
    company_id: UUID
    customer_id: UUID
    role: CustomerContactRole
    kind: CustomerContactKind
    value: str
    name: str | None
    is_primary: bool

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.company_id, self.customer_id)
        ):
            raise ValueError("Contact identity, customer and company scope must be UUIDs.")
        if not isinstance(self.role, CustomerContactRole):
            raise ValueError("role must be an official customer contact role.")
        if not isinstance(self.kind, CustomerContactKind):
            raise ValueError("kind must be an official customer contact kind.")
        if not 3 <= len(self.value) <= 180 or self.value != self.value.strip():
            raise ValueError("value must contain 3 to 180 trimmed characters.")
        if self.kind is CustomerContactKind.EMAIL and not _is_email(self.value):
            raise ValueError("EMAIL contacts require a valid e-mail address.")
        if self.kind is CustomerContactKind.PHONE and not _is_phone(self.value):
            raise ValueError("PHONE contacts require a valid phone value.")
        if self.name is not None and (
            not 1 <= len(self.name) <= 120 or self.name != self.name.strip()
        ):
            raise ValueError("name must contain 1 to 120 trimmed characters when present.")
        if type(self.is_primary) is not bool:
            raise ValueError("is_primary must be a boolean.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        customer_id: UUID,
        role: CustomerContactRole,
        kind: CustomerContactKind,
        value: str,
        name: str | None = None,
        is_primary: bool = False,
    ) -> CustomerContact:
        normalized_value = (
            value.strip().casefold() if kind is CustomerContactKind.EMAIL else value.strip()
        )
        normalized_name = name.strip() if name is not None else None
        return cls(
            id=uuid4(),
            company_id=company_id,
            customer_id=customer_id,
            role=role,
            kind=kind,
            value=normalized_value,
            name=normalized_name if name is not None else None,
            is_primary=is_primary,
        )


def _is_email(value: str) -> bool:
    return re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{2,30}", value) is not None


def _is_phone(value: str) -> bool:
    return re.fullmatch(r"\+?[0-9][0-9 .()/-]{1,30}[0-9]", value) is not None


__all__ = ["CustomerContact", "CustomerContactKind", "CustomerContactRole"]

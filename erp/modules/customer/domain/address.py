"""Customer addresses owned by the M14 aggregate boundary."""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


class CustomerAddressRole(StrEnum):
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    COMMERCIAL = "COMMERCIAL"
    FISCAL = "FISCAL"


@dataclass(frozen=True, slots=True)
class CustomerAddress:
    id: UUID
    company_id: UUID
    customer_id: UUID
    role: CustomerAddressRole
    line1: str
    city: str
    state: str
    postal_code: str
    country_code: str
    line2: str | None
    district: str | None
    is_primary: bool

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.company_id, self.customer_id)
        ):
            raise ValueError("Address identity, customer and company scope must be UUIDs.")
        if not isinstance(self.role, CustomerAddressRole):
            raise ValueError("role must be an official customer address role.")
        _trimmed(self.line1, field="line1", minimum=1, maximum=180)
        _trimmed(self.city, field="city", minimum=1, maximum=120)
        if re.fullmatch(r"[A-Z]{2}", self.state) is None:
            raise ValueError("state must be a two-letter uppercase code.")
        if re.fullmatch(r"[0-9]{8}", self.postal_code) is None:
            raise ValueError("postal_code must contain exactly eight digits.")
        if re.fullmatch(r"[A-Z]{2}", self.country_code) is None:
            raise ValueError("country_code must be a two-letter uppercase code.")
        if self.line2 is not None:
            _trimmed(self.line2, field="line2", minimum=1, maximum=180)
        if self.district is not None:
            _trimmed(self.district, field="district", minimum=1, maximum=120)
        if type(self.is_primary) is not bool:
            raise ValueError("is_primary must be a boolean.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        customer_id: UUID,
        role: CustomerAddressRole,
        line1: str,
        city: str,
        state: str,
        postal_code: str,
        country_code: str = "BR",
        line2: str | None = None,
        district: str | None = None,
        is_primary: bool = False,
    ) -> CustomerAddress:
        return cls(
            id=uuid4(),
            company_id=company_id,
            customer_id=customer_id,
            role=role,
            line1=line1.strip(),
            city=city.strip(),
            state=state.strip().upper(),
            postal_code="".join(character for character in postal_code if character.isdigit()),
            country_code=country_code.strip().upper(),
            line2=line2.strip() if line2 is not None else None,
            district=district.strip() if district is not None else None,
            is_primary=is_primary,
        )


def _trimmed(value: str, *, field: str, minimum: int, maximum: int) -> None:
    if not minimum <= len(value) <= maximum or value != value.strip():
        raise ValueError(f"{field} must contain {minimum} to {maximum} trimmed characters.")


__all__ = ["CustomerAddress", "CustomerAddressRole"]

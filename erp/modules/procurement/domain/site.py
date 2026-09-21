"""Supplier establishments and their contact/address value objects."""

import re
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from erp.modules.procurement.domain.exceptions import InvalidSupplierDataError


@dataclass(frozen=True, slots=True)
class SupplierAddress:
    line1: str
    city: str
    country_code: str
    state: str | None
    postal_code: str | None
    line2: str | None = None
    district: str | None = None

    def __post_init__(self) -> None:
        _trimmed(self.line1, "line1", 1, 180)
        _trimmed(self.city, "city", 1, 120)
        if re.fullmatch(r"[A-Z]{2}", self.country_code) is None:
            raise InvalidSupplierDataError("country_code must use ISO alpha-2 format.")
        if self.country_code == "BR":
            if self.state is None or re.fullmatch(r"[A-Z]{2}", self.state) is None:
                raise InvalidSupplierDataError("Brazilian sites require a two-letter state.")
            if self.postal_code is None or re.fullmatch(r"[0-9]{8}", self.postal_code) is None:
                raise InvalidSupplierDataError("Brazilian sites require an eight-digit postal code.")
        else:
            if self.state is not None:
                _trimmed(self.state, "state", 1, 80)
            if self.postal_code is not None and re.fullmatch(
                r"[A-Z0-9][A-Z0-9 -]{1,19}", self.postal_code
            ) is None:
                raise InvalidSupplierDataError("foreign postal_code is invalid.")
        if self.line2 is not None:
            _trimmed(self.line2, "line2", 1, 180)
        if self.district is not None:
            _trimmed(self.district, "district", 1, 120)

    @classmethod
    def create(
        cls,
        *,
        line1: str,
        city: str,
        country_code: str,
        state: str | None = None,
        postal_code: str | None = None,
        line2: str | None = None,
        district: str | None = None,
    ) -> SupplierAddress:
        country = country_code.strip().upper()
        normalized_postal = postal_code.strip().upper() if postal_code is not None else None
        if country == "BR" and normalized_postal is not None:
            normalized_postal = "".join(char for char in normalized_postal if char.isdigit())
        return cls(
            line1=line1.strip(),
            city=city.strip(),
            country_code=country,
            state=state.strip().upper() if state is not None else None,
            postal_code=normalized_postal,
            line2=line2.strip() if line2 is not None else None,
            district=district.strip() if district is not None else None,
        )


@dataclass(frozen=True, slots=True)
class SupplierSite:
    id: UUID
    company_id: UUID
    supplier_id: UUID
    code: str
    name: str
    address: SupplierAddress
    email: str | None
    phone: str | None
    is_primary: bool
    active: bool

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (self.id, self.company_id, self.supplier_id)):
            raise InvalidSupplierDataError("site identity and scope must be UUIDs.")
        if re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,31}", self.code) is None:
            raise InvalidSupplierDataError("site code must use 1 to 32 safe uppercase characters.")
        _trimmed(self.name, "site name", 1, 160)
        if not isinstance(self.address, SupplierAddress):
            raise InvalidSupplierDataError("address must be a validated SupplierAddress.")
        if self.email is not None and re.fullmatch(
            r"[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{2,30}", self.email
        ) is None:
            raise InvalidSupplierDataError("site e-mail address is invalid.")
        if self.phone is not None and re.fullmatch(
            r"\+?[0-9][0-9 .()/-]{1,30}[0-9]", self.phone
        ) is None:
            raise InvalidSupplierDataError("site phone is invalid.")
        if type(self.is_primary) is not bool or type(self.active) is not bool:
            raise InvalidSupplierDataError("site flags must be booleans.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        supplier_id: UUID,
        code: str,
        name: str,
        address: SupplierAddress,
        email: str | None = None,
        phone: str | None = None,
        is_primary: bool = False,
    ) -> SupplierSite:
        return cls(
            id=uuid4(),
            company_id=company_id,
            supplier_id=supplier_id,
            code=code.strip().upper(),
            name=name.strip(),
            address=address,
            email=email.strip().casefold() if email is not None else None,
            phone=phone.strip() if phone is not None else None,
            is_primary=is_primary,
            active=True,
        )

    def deactivate(self) -> SupplierSite:
        return self if not self.active else replace(self, active=False)

    def activate(self) -> SupplierSite:
        return self if self.active else replace(self, active=True)


def _trimmed(value: str, field: str, minimum: int, maximum: int) -> None:
    if not minimum <= len(value) <= maximum or value != value.strip():
        raise InvalidSupplierDataError(
            f"{field} must contain {minimum} to {maximum} trimmed characters."
        )


__all__ = ["SupplierAddress", "SupplierSite"]

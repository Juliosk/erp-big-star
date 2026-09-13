"""Price-list aggregate for M9 Pricing."""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.pricing.domain.money import Money, Percentage


class PriceListStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PriceListVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class PriceType(StrEnum):
    BASE = "BASE"
    CHANNEL = "CHANNEL"
    CUSTOMER_GROUP = "CUSTOMER_GROUP"


def _identifier(value: str, *, field: str, maximum: int) -> None:
    if not 1 <= len(value) <= maximum or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*", value) is None:
        raise ValueError(f"{field} must be a canonical identifier of 1 to {maximum} characters.")


@dataclass(frozen=True, slots=True)
class PriceListItem:
    id: UUID
    company_id: UUID
    version_id: UUID
    product_id: UUID
    price: Money
    minimum_price: Money | None
    target_margin: Percentage | None

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (self.id, self.company_id, self.version_id, self.product_id)):
            raise ValueError("price-list item identities must be UUIDs.")
        if self.minimum_price is not None and self.minimum_price.amount > self.price.amount:
            raise ValueError("minimum price cannot be above the approved price.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        version_id: UUID,
        product_id: UUID,
        price: Money,
        minimum_price: Money | None = None,
        target_margin: Percentage | None = None,
    ) -> PriceListItem:
        return cls(
            id=uuid4(),
            company_id=company_id,
            version_id=version_id,
            product_id=product_id,
            price=price,
            minimum_price=minimum_price,
            target_margin=target_margin,
        )


@dataclass(frozen=True, slots=True)
class PriceListVersion:
    id: UUID
    company_id: UUID
    price_list_id: UUID
    version_number: int
    status: PriceListVersionStatus
    valid_from: date
    valid_to: date | None
    source: str
    items: tuple[PriceListItem, ...]
    activated_at: datetime | None
    version: int

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (self.id, self.company_id, self.price_list_id)):
            raise ValueError("price-list version identities must be UUIDs.")
        if type(self.version_number) is not int or self.version_number < 1:
            raise ValueError("version number must be a positive integer.")
        if not isinstance(self.status, PriceListVersionStatus):
            raise ValueError("status must be an official price-list version status.")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be before valid_from.")
        _identifier(self.source, field="source", maximum=32)
        if self.status is PriceListVersionStatus.ACTIVE and self.activated_at is None:
            raise ValueError("active price-list version must have activation timestamp.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")
        for item in self.items:
            if item.company_id != self.company_id or item.version_id != self.id:
                raise ValueError("price-list items must belong to the same company and version.")

    @classmethod
    def draft(
        cls,
        *,
        company_id: UUID,
        price_list_id: UUID,
        version_number: int,
        valid_from: date,
        valid_to: date | None = None,
        source: str = "MANUAL",
        items: tuple[PriceListItem, ...] = (),
    ) -> PriceListVersion:
        version_id = uuid4()
        return cls(
            id=version_id,
            company_id=company_id,
            price_list_id=price_list_id,
            version_number=version_number,
            status=PriceListVersionStatus.DRAFT,
            valid_from=valid_from,
            valid_to=valid_to,
            source=source.strip().upper(),
            items=tuple(
                replace(item, version_id=version_id, company_id=company_id) for item in items
            ),
            activated_at=None,
            version=1,
        )

    def activate(self, activated_at: datetime) -> PriceListVersion:
        if self.status is not PriceListVersionStatus.DRAFT:
            raise ValueError("only draft price-list versions can be activated.")
        if not self.items:
            raise ValueError("price-list version cannot be activated without items.")
        return replace(
            self,
            status=PriceListVersionStatus.ACTIVE,
            activated_at=activated_at,
            version=self.version + 1,
        )

    def supersede(self) -> PriceListVersion:
        if self.status is not PriceListVersionStatus.ACTIVE:
            raise ValueError("only active price-list versions can be superseded.")
        return replace(self, status=PriceListVersionStatus.SUPERSEDED, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class PriceList:
    id: UUID
    company_id: UUID
    code: str
    name: str
    price_type: PriceType
    currency: str
    status: PriceListStatus
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise ValueError("price-list identity and company scope must be UUIDs.")
        _identifier(self.code, field="code", maximum=64)
        if not 1 <= len(self.name) <= 160 or self.name != self.name.strip():
            raise ValueError("name must contain 1 to 160 trimmed characters.")
        if not isinstance(self.price_type, PriceType):
            raise ValueError("price_type must be an official M9 type.")
        if self.currency != "BRL":
            raise ValueError("M9 initial slice supports BRL only.")
        if not isinstance(self.status, PriceListStatus):
            raise ValueError("status must be an official price-list status.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        name: str,
        price_type: PriceType = PriceType.BASE,
        currency: str = "BRL",
    ) -> PriceList:
        return cls(
            id=uuid4(),
            company_id=company_id,
            code=code.strip().upper(),
            name=name.strip(),
            price_type=price_type,
            currency=currency.strip().upper(),
            status=PriceListStatus.ACTIVE,
            version=1,
        )


__all__ = [
    "PriceList",
    "PriceListItem",
    "PriceListStatus",
    "PriceListVersion",
    "PriceListVersionStatus",
    "PriceType",
]

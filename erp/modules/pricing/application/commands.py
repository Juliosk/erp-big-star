"""Application ports and command DTOs for M9 Pricing."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from erp.modules.pricing.domain import PriceList, PriceListStatus, PriceListVersion, PriceType


@dataclass(frozen=True, slots=True)
class PricingPage[T]:
    items: tuple[T, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class CreatePriceList:
    company_id: UUID
    code: str
    name: str
    price_type: PriceType = PriceType.BASE
    currency: str = "BRL"


@dataclass(frozen=True, slots=True)
class CreatePriceListVersion:
    company_id: UUID
    price_list_id: UUID
    valid_from: date
    valid_to: date | None = None
    source: str = "MANUAL"


class PricingCatalogStore(Protocol):
    async def create_price_list(self, price_list: PriceList, actor_id: UUID) -> PriceList: ...

    async def create_price_list_version(
        self, version: PriceListVersion, actor_id: UUID
    ) -> PriceListVersion: ...


class PricingDirectory(Protocol):
    async def get_price_list(self, company_id: UUID, price_list_id: UUID) -> PriceList | None: ...

    async def list_price_lists(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PriceListStatus | None,
    ) -> PricingPage[PriceList]: ...

    async def next_version_number(self, company_id: UUID, price_list_id: UUID) -> int: ...

    async def list_price_list_versions(
        self,
        company_id: UUID,
        price_list_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> PricingPage[PriceListVersion]: ...


class PricingCatalogue(PricingCatalogStore, PricingDirectory, Protocol):
    """Combined port used by the composition root."""


def validate_pagination(page: int, page_size: int) -> None:
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive integer.")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size must be an integer between 1 and 100.")


def tuple_page[T](items: Sequence[T], *, page: int, page_size: int) -> PricingPage[T]:
    validate_pagination(page, page_size)
    return PricingPage(tuple(items[:page_size]), page, page_size, len(items) > page_size)


__all__ = [
    "CreatePriceList",
    "CreatePriceListVersion",
    "PricingCatalogStore",
    "PricingCatalogue",
    "PricingDirectory",
    "PricingPage",
    "tuple_page",
    "validate_pagination",
]

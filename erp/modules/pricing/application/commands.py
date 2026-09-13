"""Application ports and command DTOs for M9 Pricing."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from erp.modules.pricing.domain import (
    Money,
    Percentage,
    PriceList,
    PriceListItem,
    PriceListStatus,
    PriceListVersion,
    PriceListVersionStatus,
    PriceType,
)


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
class CreatePriceListItem:
    product_id: UUID
    price_amount: Decimal
    minimum_price_amount: Decimal | None = None
    target_margin: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CreatePriceListVersion:
    company_id: UUID
    price_list_id: UUID
    valid_from: date
    valid_to: date | None = None
    source: str = "MANUAL"
    items: tuple[CreatePriceListItem, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class ActivatePriceListVersion:
    company_id: UUID
    price_list_version_id: UUID
    expected_version: int
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "price_list_version_id": str(self.price_list_version_id),
            "expected_version": self.expected_version,
        }


def price_list_snapshot(price_list: PriceList) -> dict[str, object]:
    return {
        "id": str(price_list.id),
        "company_id": str(price_list.company_id),
        "code": price_list.code,
        "name": price_list.name,
        "price_type": price_list.price_type,
        "currency": price_list.currency,
        "status": price_list.status,
        "version": price_list.version,
    }


def price_list_version_snapshot(version: PriceListVersion) -> dict[str, object]:
    return {
        "id": str(version.id),
        "company_id": str(version.company_id),
        "price_list_id": str(version.price_list_id),
        "version_number": version.version_number,
        "status": version.status,
        "valid_from": version.valid_from.isoformat(),
        "valid_to": version.valid_to.isoformat() if version.valid_to is not None else None,
        "source": version.source,
        "activated_at": version.activated_at.isoformat()
        if version.activated_at is not None
        else None,
        "version": version.version,
        "items": [
            {
                "id": str(item.id),
                "product_id": str(item.product_id),
                "price": f"{item.price.amount:.2f}",
                "minimum_price": f"{item.minimum_price.amount:.2f}"
                if item.minimum_price is not None
                else None,
                "target_margin": f"{item.target_margin.value:.4f}"
                if item.target_margin is not None
                else None,
                "currency": item.price.currency,
            }
            for item in version.items
        ],
    }


@dataclass(frozen=True, slots=True)
class PricingCommandResult:
    price_list_version: PriceListVersion
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "price_list_version": price_list_version_snapshot(self.price_list_version),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id)
            if self.audit_event_id is not None
            else None,
            "idempotency_replayed": self.idempotency_replayed,
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> PricingCommandResult:
        item = body["price_list_version"]
        return cls(
            price_list_version=PriceListVersion(
                id=UUID(item["id"]),
                company_id=UUID(item["company_id"]),
                price_list_id=UUID(item["price_list_id"]),
                version_number=item["version_number"],
                status=PriceListVersionStatus(item["status"]),
                valid_from=date.fromisoformat(item["valid_from"]),
                valid_to=date.fromisoformat(item["valid_to"])
                if item["valid_to"] is not None
                else None,
                source=item["source"],
                activated_at=datetime.fromisoformat(item["activated_at"])
                if item["activated_at"] is not None
                else None,
                items=tuple(
                    PriceListItem(
                        id=UUID(row["id"]),
                        company_id=UUID(item["company_id"]),
                        version_id=UUID(item["id"]),
                        product_id=UUID(row["product_id"]),
                        price=Money.brl(row["price"]),
                        minimum_price=Money.brl(row["minimum_price"])
                        if row["minimum_price"] is not None
                        else None,
                        target_margin=Percentage.ratio(row["target_margin"])
                        if row["target_margin"] is not None
                        else None,
                    )
                    for row in item["items"]
                ),
                version=item["version"],
            ),
            event_id=UUID(body["event_id"]) if body["event_id"] is not None else None,
            audit_event_id=UUID(body["audit_event_id"])
            if body["audit_event_id"] is not None
            else None,
            idempotency_replayed=True,
        )


class PricingCatalogStore(Protocol):
    async def create_price_list(self, price_list: PriceList, actor_id: UUID) -> PriceList: ...

    async def create_price_list_version(
        self, version: PriceListVersion, actor_id: UUID
    ) -> PriceListVersion: ...

    async def activate_price_list_version(
        self, command: ActivatePriceListVersion, actor_id: UUID
    ) -> PricingCommandResult: ...


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

    async def get_price_list_version(
        self, company_id: UUID, price_list_version_id: UUID
    ) -> PriceListVersion | None: ...


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
    "ActivatePriceListVersion",
    "CommandMetadata",
    "CreatePriceList",
    "CreatePriceListItem",
    "CreatePriceListVersion",
    "PricingCatalogStore",
    "PricingCatalogue",
    "PricingCommandResult",
    "PricingDirectory",
    "PricingPage",
    "price_list_snapshot",
    "price_list_version_snapshot",
    "tuple_page",
    "validate_pagination",
]

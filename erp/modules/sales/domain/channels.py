"""Immutable canonical channel orders; no transport or persistence dependencies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class SalesChannelError(ValueError):
    code = "INVALID_CHANNEL_ORDER"


class SalesChannelScopeError(SalesChannelError):
    code = "SALES_CHANNEL_SCOPE_VIOLATION"


class SalesChannelConflictError(SalesChannelError):
    code = "SALES_CHANNEL_CONFLICT"


class SalesChannelVersionConflictError(SalesChannelError):
    code = "VERSION_CONFLICT"

    def __init__(self, expected_version: int) -> None:
        self.expected_version = expected_version
        super().__init__(f"The sales channel resource changed after version {expected_version}.")


class Marketplace(StrEnum):
    MERCADO_LIVRE = "MERCADO_LIVRE"
    SHOPEE = "SHOPEE"
    NUVEMSHOP = "NUVEMSHOP"


class ChannelOrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ChannelFee:
    """Normalized channel charge kept separate from merchandise revenue."""

    code: str
    amount: Decimal

    def __post_init__(self) -> None:
        _text(self.code)
        _decimal(self.amount, "0.01")


@dataclass(frozen=True, slots=True)
class ExternalChannelOrderItem:
    """Transport-neutral item before M3 resolves the M2 product De/Para."""

    external_item_id: str
    listing_id: str
    variation_id: str
    external_sku: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        _text(self.external_item_id)
        _text(self.listing_id)
        _text(self.variation_id)
        _text(self.external_sku)
        _decimal(self.quantity, "0.000001", positive=True)
        _decimal(self.unit_price, "0.01", positive=True)
        _decimal(self.discount_amount, "0.01")
        if self.discount_amount > _money(self.quantity * self.unit_price):
            raise SalesChannelError("External item discount exceeds gross amount.")


@dataclass(frozen=True, slots=True)
class ExternalChannelOrder:
    """Canonical marketplace payload before tenant-bound SKU resolution."""

    reference: ChannelOrderReference
    status: ChannelOrderStatus
    items: tuple[ExternalChannelOrderItem, ...]
    freight_amount: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    fees: tuple[ChannelFee, ...] = ()
    currency: str = "BRL"

    def __post_init__(self) -> None:
        if not isinstance(self.reference, ChannelOrderReference):
            raise SalesChannelError("A scoped reference is required.")
        if not isinstance(self.status, ChannelOrderStatus):
            raise SalesChannelError("Unknown channel status.")
        if not isinstance(self.items, tuple) or not self.items:
            raise SalesChannelError("An immutable non-empty external item tuple is required.")
        if self.currency != "BRL":
            raise SalesChannelError("Initial channel slice supports BRL only.")
        if any(not isinstance(item, ExternalChannelOrderItem) for item in self.items):
            raise SalesChannelError("Invalid external channel item.")
        if len({item.external_item_id for item in self.items}) != len(self.items):
            raise SalesChannelError("Duplicate external item identity.")
        if not isinstance(self.fees, tuple) or any(
            not isinstance(fee, ChannelFee) for fee in self.fees
        ):
            raise SalesChannelError("Channel fees must be an immutable normalized tuple.")
        _decimal(self.freight_amount, "0.01")
        _decimal(self.discount_amount, "0.01")

    @property
    def total_fees(self) -> Decimal:
        return sum((fee.amount for fee in self.fees), Decimal("0.00"))


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise SalesChannelError("Identity must be a non-zero UUID.")


def _text(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value != value.strip():
        raise SalesChannelError("Identifier must contain 1 to 128 trimmed characters.")


def _version(value: int) -> None:
    if type(value) is not int or value < 1:
        raise SalesChannelError("Record version must be a positive integer.")


def _decimal(value: Decimal, precision: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SalesChannelError("A finite Decimal is required.")
    if value < 0 or (positive and value == 0):
        raise SalesChannelError("Amount is outside its permitted range.")
    # Bound before quantizing so malformed/excessive input remains a domain error.
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)  # Finite Decimals always have an integer exponent.
    if value >= Decimal("1000000000000") or exponent < -6:
        raise SalesChannelError("Amount exceeds the supported precision.")
    if value != value.quantize(Decimal(precision)):
        raise SalesChannelError("Amount has unsupported fractional precision.")


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ChannelOrderReference:
    company_id: UUID
    account_id: UUID
    marketplace: Marketplace
    external_order_id: str

    def __post_init__(self) -> None:
        _uuid(self.company_id)
        _uuid(self.account_id)
        if not isinstance(self.marketplace, Marketplace):
            raise SalesChannelError("Unknown marketplace.")
        _text(self.external_order_id)

    @property
    def ingestion_key(self) -> tuple[UUID, Marketplace, UUID, str]:
        return self.company_id, self.marketplace, self.account_id, self.external_order_id


@dataclass(frozen=True, slots=True)
class ChannelSkuMapping:
    company_id: UUID
    account_id: UUID
    marketplace: Marketplace
    listing_id: str
    variation_id: str
    external_sku: str
    product_id: UUID

    def __post_init__(self) -> None:
        ChannelOrderReference(self.company_id, self.account_id, self.marketplace, self.listing_id)
        _text(self.variation_id)
        _text(self.external_sku)
        _uuid(self.product_id)

    def require_scope(self, reference: ChannelOrderReference) -> None:
        if (self.company_id, self.account_id, self.marketplace) != (
            reference.company_id,
            reference.account_id,
            reference.marketplace,
        ):
            raise SalesChannelError("SKU mapping crosses the company/account/channel boundary.")


@dataclass(frozen=True, slots=True)
class ChannelOrderItem:
    external_item_id: str
    mapping: ChannelSkuMapping
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        _text(self.external_item_id)
        if not isinstance(self.mapping, ChannelSkuMapping):
            raise SalesChannelError("An explicit SKU mapping is required.")
        _decimal(self.quantity, "0.000001", positive=True)
        _decimal(self.unit_price, "0.01", positive=True)
        _decimal(self.discount_amount, "0.01")
        if self.discount_amount > self.gross_amount:
            raise SalesChannelError("Item discount exceeds gross amount.")

    @property
    def gross_amount(self) -> Decimal:
        return _money(self.quantity * self.unit_price)

    @property
    def net_amount(self) -> Decimal:
        return self.gross_amount - self.discount_amount


@dataclass(frozen=True, slots=True)
class ChannelOrderSnapshot:
    reference: ChannelOrderReference
    status: ChannelOrderStatus
    items: tuple[ChannelOrderItem, ...]
    freight_amount: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    currency: str = "BRL"

    def __post_init__(self) -> None:
        if not isinstance(self.reference, ChannelOrderReference):
            raise SalesChannelError("A scoped reference is required.")
        if not isinstance(self.status, ChannelOrderStatus):
            raise SalesChannelError("Unknown channel status.")
        if not isinstance(self.items, tuple) or not self.items:
            raise SalesChannelError("An immutable non-empty item tuple is required.")
        if self.currency != "BRL":
            raise SalesChannelError("Initial channel slice supports BRL only.")
        for item in self.items:
            if not isinstance(item, ChannelOrderItem):
                raise SalesChannelError("Invalid channel item.")
            item.mapping.require_scope(self.reference)
        if len({item.external_item_id for item in self.items}) != len(self.items):
            raise SalesChannelError("Duplicate external item identity.")
        _decimal(self.freight_amount, "0.01")
        _decimal(self.discount_amount, "0.01")
        if self.discount_amount > self.merchandise_amount:
            raise SalesChannelError("Order discount exceeds merchandise amount.")

    @property
    def merchandise_amount(self) -> Decimal:
        return sum((item.net_amount for item in self.items), Decimal("0.00"))

    @property
    def total_amount(self) -> Decimal:
        return self.merchandise_amount - self.discount_amount + self.freight_amount

    def transition(self, target: ChannelOrderStatus) -> ChannelOrderSnapshot:
        allowed = {
            ChannelOrderStatus.PENDING: {ChannelOrderStatus.PAID, ChannelOrderStatus.CANCELLED},
            ChannelOrderStatus.PAID: {ChannelOrderStatus.SHIPPED, ChannelOrderStatus.CANCELLED},
            ChannelOrderStatus.SHIPPED: set(),
            ChannelOrderStatus.CANCELLED: set(),
        }
        if target not in allowed[self.status]:
            raise SalesChannelError("Invalid channel status transition.")
        return replace(self, status=target)


def channel_order_fingerprint(snapshot: ChannelOrderSnapshot) -> str:
    """Return a stable SHA-256 for normalized replay detection."""

    if not isinstance(snapshot, ChannelOrderSnapshot):
        raise SalesChannelError("A channel order snapshot is required.")
    payload = {
        "reference": {
            "company_id": str(snapshot.reference.company_id),
            "account_id": str(snapshot.reference.account_id),
            "marketplace": snapshot.reference.marketplace.value,
            "external_order_id": snapshot.reference.external_order_id,
        },
        "status": snapshot.status.value,
        "currency": snapshot.currency,
        "freight_amount": str(snapshot.freight_amount),
        "discount_amount": str(snapshot.discount_amount),
        "items": [
            {
                "external_item_id": item.external_item_id,
                "listing_id": item.mapping.listing_id,
                "variation_id": item.mapping.variation_id,
                "external_sku": item.mapping.external_sku,
                "product_id": str(item.mapping.product_id),
                "quantity": str(item.quantity),
                "unit_price": str(item.unit_price),
                "discount_amount": str(item.discount_amount),
            }
            for item in snapshot.items
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SalesChannelAccount:
    """Tenant-bound configuration that stores only an external secret reference."""

    id: UUID
    company_id: UUID
    account_id: UUID
    marketplace: Marketplace
    display_name: str
    credential_reference: str
    active: bool = True
    record_version: int = 1

    def __post_init__(self) -> None:
        _uuid(self.id)
        _uuid(self.company_id)
        _uuid(self.account_id)
        if not isinstance(self.marketplace, Marketplace):
            raise SalesChannelError("Unknown marketplace.")
        _text(self.display_name)
        if (
            not isinstance(self.credential_reference, str)
            or not 1 <= len(self.credential_reference) <= 255
            or self.credential_reference != self.credential_reference.strip()
        ):
            raise SalesChannelError("Credential reference must contain trimmed text.")
        if type(self.active) is not bool:
            raise SalesChannelError("Channel active flag must be boolean.")
        _version(self.record_version)

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        account_id: UUID,
        marketplace: Marketplace,
        display_name: str,
        credential_reference: str,
    ) -> SalesChannelAccount:
        return cls(
            id=uuid4(),
            company_id=company_id,
            account_id=account_id,
            marketplace=marketplace,
            display_name=display_name,
            credential_reference=credential_reference,
        )

    def set_active(self, active: bool) -> SalesChannelAccount:
        if type(active) is not bool or active is self.active:
            raise SalesChannelError("Channel state must change explicitly.")
        return replace(self, active=active, record_version=self.record_version + 1)


@dataclass(frozen=True, slots=True)
class ChannelSkuMappingEntry:
    id: UUID
    channel_config_id: UUID
    mapping: ChannelSkuMapping
    active: bool = True
    record_version: int = 1

    def __post_init__(self) -> None:
        _uuid(self.id)
        _uuid(self.channel_config_id)
        if not isinstance(self.mapping, ChannelSkuMapping):
            raise SalesChannelError("A valid SKU mapping is required.")
        if type(self.active) is not bool:
            raise SalesChannelError("Mapping active flag must be boolean.")
        _version(self.record_version)

    @classmethod
    def create(
        cls, *, channel_config_id: UUID, mapping: ChannelSkuMapping
    ) -> ChannelSkuMappingEntry:
        return cls(uuid4(), channel_config_id, mapping)

    def remap(self, product_id: UUID) -> ChannelSkuMappingEntry:
        _uuid(product_id)
        return replace(
            self,
            mapping=replace(self.mapping, product_id=product_id),
            record_version=self.record_version + 1,
        )


@dataclass(frozen=True, slots=True)
class MultichannelSalesOrder:
    id: UUID
    channel_config_id: UUID
    snapshot: ChannelOrderSnapshot
    source_fingerprint: str
    record_version: int = 1

    def __post_init__(self) -> None:
        _uuid(self.id)
        _uuid(self.channel_config_id)
        if not isinstance(self.snapshot, ChannelOrderSnapshot):
            raise SalesChannelError("A valid channel order snapshot is required.")
        if (
            not isinstance(self.source_fingerprint, str)
            or len(self.source_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.source_fingerprint)
        ):
            raise SalesChannelError("Source fingerprint must be a lowercase SHA-256 digest.")
        _version(self.record_version)

    @classmethod
    def capture(
        cls,
        *,
        channel_config_id: UUID,
        snapshot: ChannelOrderSnapshot,
        order_id: UUID | None = None,
    ) -> MultichannelSalesOrder:
        return cls(
            id=order_id or uuid4(),
            channel_config_id=channel_config_id,
            snapshot=snapshot,
            source_fingerprint=channel_order_fingerprint(snapshot),
        )

    def revise(self, snapshot: ChannelOrderSnapshot) -> MultichannelSalesOrder:
        if snapshot.reference != self.snapshot.reference:
            raise SalesChannelError("An order revision cannot change its external identity.")
        return replace(
            self,
            snapshot=snapshot,
            source_fingerprint=channel_order_fingerprint(snapshot),
            record_version=self.record_version + 1,
        )


@dataclass(frozen=True, slots=True)
class ChannelMarginAnalysis:
    """Commercial analysis only; M9 owns price resolution and authorization."""

    revenue: Decimal
    product_cost: Decimal
    channel_fees: Decimal = Decimal("0.00")
    freight_cost: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        _decimal(self.revenue, "0.01", positive=True)
        _decimal(self.product_cost, "0.01")
        _decimal(self.channel_fees, "0.01")
        _decimal(self.freight_cost, "0.01")

    @property
    def contribution_amount(self) -> Decimal:
        return self.revenue - self.product_cost - self.channel_fees - self.freight_cost

    @property
    def margin_ratio(self) -> Decimal:
        return self.contribution_amount / self.revenue

    def meets(self, minimum_margin: Decimal) -> bool:
        _decimal(minimum_margin, "0.000001")
        if minimum_margin >= 1:
            raise SalesChannelError("Minimum margin must be a ratio below one.")
        return self.margin_ratio >= minimum_margin


__all__ = [
    "ChannelFee",
    "ChannelMarginAnalysis",
    "ChannelOrderItem",
    "ChannelOrderReference",
    "ChannelOrderSnapshot",
    "ChannelOrderStatus",
    "ChannelSkuMapping",
    "ChannelSkuMappingEntry",
    "ExternalChannelOrder",
    "ExternalChannelOrderItem",
    "Marketplace",
    "MultichannelSalesOrder",
    "SalesChannelAccount",
    "SalesChannelConflictError",
    "SalesChannelError",
    "SalesChannelScopeError",
    "SalesChannelVersionConflictError",
    "channel_order_fingerprint",
]

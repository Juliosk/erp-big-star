"""Immutable canonical channel orders; no transport or persistence dependencies."""

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID


class SalesChannelError(ValueError):
    code = "INVALID_CHANNEL_ORDER"


class Marketplace(StrEnum):
    MERCADO_LIVRE = "MERCADO_LIVRE"
    SHOPEE = "SHOPEE"
    NUVEMSHOP = "NUVEMSHOP"


class ChannelOrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise SalesChannelError("Identity must be a non-zero UUID.")


def _text(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value != value.strip():
        raise SalesChannelError("Identifier must contain 1 to 128 trimmed characters.")


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
    "ChannelMarginAnalysis",
    "ChannelOrderItem",
    "ChannelOrderReference",
    "ChannelOrderSnapshot",
    "ChannelOrderStatus",
    "ChannelSkuMapping",
    "Marketplace",
    "SalesChannelError",
]

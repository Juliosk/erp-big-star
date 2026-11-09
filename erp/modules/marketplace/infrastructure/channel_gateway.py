"""OAuth-aware deterministic marketplace adapters for homologation and webhooks."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

from erp.modules.sales.contracts import (
    ChannelFee,
    ChannelOrderReference,
    ChannelOrderStatus,
    ExternalChannelOrder,
    ExternalChannelOrderItem,
    Marketplace,
)


class MarketplacePayloadError(ValueError):
    code = "INVALID_MARKETPLACE_PAYLOAD"


@dataclass(frozen=True, slots=True)
class ChannelOAuthToken:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: datetime
    token_type: str = "Bearer"

    def __post_init__(self) -> None:
        for value in (self.access_token, self.refresh_token, self.token_type):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError("OAuth token fields must contain trimmed text.")
        if self.expires_at.tzinfo is None:
            raise ValueError("OAuth token expiration must be timezone-aware.")

    def is_usable(self, now: datetime) -> bool:
        return self.expires_at > now + timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class ChannelOAuthCredentials:
    client_id: str
    client_secret: str = field(repr=False)
    token: ChannelOAuthToken

    def __post_init__(self) -> None:
        for value in (self.client_id, self.client_secret):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError("OAuth client credentials must contain trimmed text.")


class ChannelCredentialStore(Protocol):
    async def get(self, reference: str) -> ChannelOAuthCredentials: ...

    async def save_token(self, reference: str, token: ChannelOAuthToken) -> None: ...


class MarketplaceTransport(Protocol):
    async def refresh_token(
        self, marketplace: Marketplace, credentials: ChannelOAuthCredentials
    ) -> ChannelOAuthToken: ...

    async def fetch_order(
        self,
        marketplace: Marketplace,
        external_order_id: str,
        access_token: str,
    ) -> Mapping[str, object]: ...


class InMemoryChannelCredentialStore:
    """Secret-store test double; production keeps only its reference in Sales."""

    def __init__(self, values: Mapping[str, ChannelOAuthCredentials]) -> None:
        self._values = dict(values)

    async def get(self, reference: str) -> ChannelOAuthCredentials:
        try:
            return self._values[reference]
        except KeyError as error:
            raise MarketplacePayloadError("Channel credential reference was not found.") from error

    async def save_token(self, reference: str, token: ChannelOAuthToken) -> None:
        current = await self.get(reference)
        self._values[reference] = replace(current, token=token)


class HomologationMarketplaceTransport:
    """Deterministic transport used without external network side effects."""

    def __init__(
        self,
        orders: Mapping[tuple[Marketplace, str], Mapping[str, object]],
        *,
        now: datetime | None = None,
    ) -> None:
        self._orders = {key: dict(value) for key, value in orders.items()}
        self._now = now or datetime.now(UTC)
        self.refresh_count = 0
        self.fetch_count = 0

    async def refresh_token(
        self, marketplace: Marketplace, credentials: ChannelOAuthCredentials
    ) -> ChannelOAuthToken:
        self.refresh_count += 1
        return ChannelOAuthToken(
            access_token=f"homologation-{marketplace.value.lower()}-{self.refresh_count}",
            refresh_token=credentials.token.refresh_token,
            expires_at=self._now + timedelta(hours=1),
        )

    async def fetch_order(
        self,
        marketplace: Marketplace,
        external_order_id: str,
        access_token: str,
    ) -> Mapping[str, object]:
        if not access_token:
            raise MarketplacePayloadError("OAuth access token is required.")
        self.fetch_count += 1
        try:
            return dict(self._orders[(marketplace, external_order_id)])
        except KeyError as error:
            raise MarketplacePayloadError("Homologation order was not found.") from error


class MarketplaceGatewayAdapter:
    """Normalize one vendor dialect and refresh OAuth without leaking secrets."""

    def __init__(
        self,
        marketplace: Marketplace,
        credentials: ChannelCredentialStore,
        transport: MarketplaceTransport,
        *,
        now: datetime | None = None,
    ) -> None:
        self._marketplace = marketplace
        self._credentials = credentials
        self._transport = transport
        self._fixed_now = now

    async def normalize_webhook(
        self,
        reference: ChannelOrderReference,
        payload: Mapping[str, object],
    ) -> ExternalChannelOrder:
        self._require_scope(reference)
        if self._marketplace is Marketplace.MERCADO_LIVRE:
            return _mercado_livre(reference, payload)
        if self._marketplace is Marketplace.SHOPEE:
            return _shopee(reference, payload)
        return _nuvemshop(reference, payload)

    async def fetch_order(
        self,
        reference: ChannelOrderReference,
        credential_reference: str,
    ) -> ExternalChannelOrder:
        self._require_scope(reference)
        credentials = await self._credentials.get(credential_reference)
        token = credentials.token
        now = self._fixed_now or datetime.now(UTC)
        if not token.is_usable(now):
            token = await self._transport.refresh_token(self._marketplace, credentials)
            await self._credentials.save_token(credential_reference, token)
        payload = await self._transport.fetch_order(
            self._marketplace, reference.external_order_id, token.access_token
        )
        return await self.normalize_webhook(reference, payload)

    def _require_scope(self, reference: ChannelOrderReference) -> None:
        if reference.marketplace is not self._marketplace:
            raise MarketplacePayloadError("Gateway and order marketplace do not match.")


def _mercado_livre(
    reference: ChannelOrderReference, payload: Mapping[str, object]
) -> ExternalChannelOrder:
    _require_order_id(reference, payload, "id")
    rows = _rows(payload, "order_items", "items")
    items: list[ExternalChannelOrderItem] = []
    fees: list[ChannelFee] = []
    for index, row in enumerate(rows, start=1):
        item = _mapping(row.get("item"), default=row)
        listing_id = _required_text(item.get("id", row.get("listing_id")), "listing_id")
        variation_id = _optional_text(item.get("variation_id", row.get("variation_id")), "STANDARD")
        items.append(
            ExternalChannelOrderItem(
                external_item_id=_optional_text(
                    row.get("id"), f"{listing_id}:{variation_id}:{index}"
                ),
                listing_id=listing_id,
                variation_id=variation_id,
                external_sku=_required_text(
                    item.get("seller_sku", row.get("sku", row.get("external_sku"))),
                    "external_sku",
                ),
                quantity=_decimal(row.get("quantity"), "quantity"),
                unit_price=_decimal(row.get("unit_price", row.get("price")), "unit_price"),
                discount_amount=_decimal(row.get("discount_amount", "0.00"), "discount_amount"),
            )
        )
        fee = _decimal(row.get("sale_fee", "0.00"), "sale_fee")
        if fee:
            fees.append(ChannelFee("MARKETPLACE_FEE", fee))
    return _order(
        reference,
        payload,
        _status(payload, "status", _ML_STATUSES),
        tuple(items),
        tuple(fees) + _payload_fees(payload),
    )


def _shopee(
    reference: ChannelOrderReference, payload: Mapping[str, object]
) -> ExternalChannelOrder:
    _require_order_id(reference, payload, "ordersn", "id")
    rows = _rows(payload, "item_list", "items")
    items: list[ExternalChannelOrderItem] = []
    for index, row in enumerate(rows, start=1):
        listing_id = _required_text(row.get("item_id", row.get("listing_id")), "listing_id")
        variation_id = _optional_text(row.get("model_id", row.get("variation_id")), "STANDARD")
        items.append(
            ExternalChannelOrderItem(
                external_item_id=_optional_text(
                    row.get("order_item_id"), f"{listing_id}:{variation_id}:{index}"
                ),
                listing_id=listing_id,
                variation_id=variation_id,
                external_sku=_required_text(
                    row.get("model_sku", row.get("item_sku", row.get("sku"))),
                    "external_sku",
                ),
                quantity=_decimal(
                    row.get("model_quantity_purchased", row.get("quantity")), "quantity"
                ),
                unit_price=_decimal(
                    row.get("model_discounted_price", row.get("unit_price", row.get("price"))),
                    "unit_price",
                ),
                discount_amount=_decimal(row.get("discount_amount", "0.00"), "discount_amount"),
            )
        )
    fees = list(_payload_fees(payload))
    for key, code in (("commission_fee", "COMMISSION"), ("service_fee", "SERVICE_FEE")):
        amount = _decimal(payload.get(key, "0.00"), key)
        if amount:
            fees.append(ChannelFee(code, amount))
    return _order(
        reference,
        payload,
        _status(payload, "order_status", _SHOPEE_STATUSES, fallback="status"),
        tuple(items),
        tuple(fees),
    )


def _nuvemshop(
    reference: ChannelOrderReference, payload: Mapping[str, object]
) -> ExternalChannelOrder:
    _require_order_id(reference, payload, "id")
    rows = _rows(payload, "products", "items")
    items = tuple(
        ExternalChannelOrderItem(
            external_item_id=_optional_text(row.get("id"), f"item-{index}"),
            listing_id=_required_text(
                row.get("product_id", row.get("listing_id", row.get("id"))),
                "listing_id",
            ),
            variation_id=_optional_text(row.get("variant_id", row.get("variation_id")), "STANDARD"),
            external_sku=_required_text(row.get("sku", row.get("external_sku")), "external_sku"),
            quantity=_decimal(row.get("quantity"), "quantity"),
            unit_price=_decimal(row.get("price", row.get("unit_price")), "unit_price"),
            discount_amount=_decimal(row.get("discount_amount", "0.00"), "discount_amount"),
        )
        for index, row in enumerate(rows, start=1)
    )
    return _order(
        reference,
        payload,
        _status(payload, "status", _NUVEMSHOP_STATUSES),
        items,
        _payload_fees(payload),
    )


def _order(
    reference: ChannelOrderReference,
    payload: Mapping[str, object],
    status: ChannelOrderStatus,
    items: tuple[ExternalChannelOrderItem, ...],
    fees: tuple[ChannelFee, ...],
) -> ExternalChannelOrder:
    return ExternalChannelOrder(
        reference=reference,
        status=status,
        items=items,
        freight_amount=_decimal(
            payload.get("freight_amount", payload.get("shipping_cost", "0.00")),
            "freight_amount",
        ),
        discount_amount=_decimal(payload.get("discount_amount", "0.00"), "discount_amount"),
        fees=fees,
        currency=_optional_text(payload.get("currency"), "BRL"),
    )


def _payload_fees(payload: Mapping[str, object]) -> tuple[ChannelFee, ...]:
    raw = payload.get("fees", ())
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise MarketplacePayloadError("fees must be a list.")
    return tuple(
        ChannelFee(
            _required_text(_mapping(value).get("type", _mapping(value).get("code")), "fee.type"),
            _decimal(_mapping(value).get("amount"), "fee.amount"),
        )
        for value in raw
    )


def _require_order_id(
    reference: ChannelOrderReference, payload: Mapping[str, object], *keys: str
) -> None:
    value: object | None = None
    for key in keys:
        if payload.get(key) is not None:
            value = payload[key]
            break
    if str(value) != reference.external_order_id:
        raise MarketplacePayloadError("Payload external order identity does not match scope.")


def _rows(
    payload: Mapping[str, object], primary: str, fallback: str
) -> tuple[Mapping[str, object], ...]:
    raw = payload.get(primary, payload.get(fallback))
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or not raw:
        raise MarketplacePayloadError("Marketplace order must contain an item list.")
    return tuple(_mapping(value) for value in raw)


def _mapping(value: object, *, default: Mapping[str, object] | None = None) -> Mapping[str, object]:
    if value is None and default is not None:
        return default
    if not isinstance(value, Mapping):
        raise MarketplacePayloadError("Marketplace object has an invalid shape.")
    return {str(key): item for key, item in value.items()}


def _required_text(value: object, field: str) -> str:
    if value is None:
        raise MarketplacePayloadError(f"{field} is required.")
    text = str(value)
    if not text or text != text.strip() or len(text) > 128:
        raise MarketplacePayloadError(f"{field} must contain trimmed text.")
    return text


def _optional_text(value: object, default: str) -> str:
    return default if value is None or value == "" else _required_text(value, "text")


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, (bool, float)) or value is None:
        raise MarketplacePayloadError(f"{field} must be an exact decimal value.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise MarketplacePayloadError(f"{field} must be an exact decimal value.") from error
    if not result.is_finite():
        raise MarketplacePayloadError(f"{field} must be finite.")
    return result


def _status(
    payload: Mapping[str, object],
    key: str,
    values: Mapping[str, ChannelOrderStatus],
    *,
    fallback: str | None = None,
) -> ChannelOrderStatus:
    raw = payload.get(key, payload.get(fallback) if fallback else None)
    normalized = str(raw).strip().upper()
    try:
        return values[normalized]
    except KeyError as error:
        raise MarketplacePayloadError("Unknown marketplace order status.") from error


_ML_STATUSES = {
    "CONFIRMED": ChannelOrderStatus.PENDING,
    "PAYMENT_REQUIRED": ChannelOrderStatus.PENDING,
    "PAID": ChannelOrderStatus.PAID,
    "SHIPPED": ChannelOrderStatus.SHIPPED,
    "CANCELLED": ChannelOrderStatus.CANCELLED,
}
_SHOPEE_STATUSES = {
    "UNPAID": ChannelOrderStatus.PENDING,
    "READY_TO_SHIP": ChannelOrderStatus.PAID,
    "PROCESSED": ChannelOrderStatus.PAID,
    "SHIPPED": ChannelOrderStatus.SHIPPED,
    "COMPLETED": ChannelOrderStatus.SHIPPED,
    "CANCELLED": ChannelOrderStatus.CANCELLED,
}
_NUVEMSHOP_STATUSES = {
    "OPEN": ChannelOrderStatus.PENDING,
    "PENDING": ChannelOrderStatus.PENDING,
    "PAID": ChannelOrderStatus.PAID,
    "SHIPPED": ChannelOrderStatus.SHIPPED,
    "CLOSED": ChannelOrderStatus.SHIPPED,
    "CANCELLED": ChannelOrderStatus.CANCELLED,
    "VOIDED": ChannelOrderStatus.CANCELLED,
}


__all__ = [
    "ChannelCredentialStore",
    "ChannelOAuthCredentials",
    "ChannelOAuthToken",
    "HomologationMarketplaceTransport",
    "InMemoryChannelCredentialStore",
    "MarketplaceGatewayAdapter",
    "MarketplacePayloadError",
    "MarketplaceTransport",
]

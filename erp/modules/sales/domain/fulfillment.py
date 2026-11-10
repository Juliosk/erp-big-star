"""Pure sales fulfillment aggregate and immutable shipping label facts."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.sales.domain.channels import Marketplace


class SalesFulfillmentError(ValueError):
    code = "INVALID_SALES_FULFILLMENT"


class SalesShipmentStatus(StrEnum):
    LABEL_CREATED = "LABEL_CREATED"
    DISPATCHED = "DISPATCHED"


@dataclass(frozen=True, slots=True)
class ShippingLabel:
    carrier_code: str
    service_code: str
    tracking_code: str
    label_reference: str

    def __post_init__(self) -> None:
        _text(self.carrier_code, field="carrier_code", max_length=32)
        _text(self.service_code, field="service_code", max_length=32)
        _text(self.tracking_code, field="tracking_code", max_length=80)
        _text(self.label_reference, field="label_reference", max_length=255)


@dataclass(frozen=True, slots=True)
class SalesShipment:
    id: UUID
    company_id: UUID
    sales_order_id: UUID
    wms_shipment_id: UUID
    channel_config_id: UUID
    account_id: UUID
    marketplace: Marketplace
    external_order_id: str
    status: SalesShipmentStatus
    label: ShippingLabel
    dispatched_at: datetime | None
    version: int

    def __post_init__(self) -> None:
        for identity in (
            self.id,
            self.company_id,
            self.sales_order_id,
            self.wms_shipment_id,
            self.channel_config_id,
            self.account_id,
        ):
            _uuid(identity)
        if not isinstance(self.marketplace, Marketplace):
            raise SalesFulfillmentError("Unknown fulfillment marketplace.")
        _text(self.external_order_id, field="external_order_id", max_length=128)
        if not isinstance(self.status, SalesShipmentStatus):
            raise SalesFulfillmentError("Unknown sales shipment status.")
        if not isinstance(self.label, ShippingLabel):
            raise SalesFulfillmentError("A validated shipping label is required.")
        if type(self.version) is not int or self.version < 1:
            raise SalesFulfillmentError("Shipment version must be positive.")
        if self.dispatched_at is not None and self.dispatched_at.tzinfo is None:
            raise SalesFulfillmentError("Dispatch timestamp must be timezone-aware.")
        if (
            self.status is SalesShipmentStatus.DISPATCHED
            and self.dispatched_at is None
        ):
            raise SalesFulfillmentError("Dispatched shipment requires a timestamp.")
        if (
            self.status is SalesShipmentStatus.LABEL_CREATED
            and self.dispatched_at is not None
        ):
            raise SalesFulfillmentError("Label-only shipment cannot be dispatched.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        sales_order_id: UUID,
        wms_shipment_id: UUID,
        channel_config_id: UUID,
        account_id: UUID,
        marketplace: Marketplace,
        external_order_id: str,
        label: ShippingLabel,
        shipment_id: UUID | None = None,
    ) -> SalesShipment:
        return cls(
            id=shipment_id or uuid4(),
            company_id=company_id,
            sales_order_id=sales_order_id,
            wms_shipment_id=wms_shipment_id,
            channel_config_id=channel_config_id,
            account_id=account_id,
            marketplace=marketplace,
            external_order_id=external_order_id,
            status=SalesShipmentStatus.LABEL_CREATED,
            label=label,
            dispatched_at=None,
            version=1,
        )

    def dispatch(self, *, now: datetime | None = None) -> SalesShipment:
        if self.status is not SalesShipmentStatus.LABEL_CREATED:
            raise SalesFulfillmentError("Only a labeled shipment can be dispatched.")
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise SalesFulfillmentError("Dispatch timestamp must be timezone-aware.")
        return replace(
            self,
            status=SalesShipmentStatus.DISPATCHED,
            dispatched_at=instant,
            version=self.version + 1,
        )


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise SalesFulfillmentError("Fulfillment identities must be non-zero UUIDs.")


def _text(value: str, *, field: str, max_length: int) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= max_length
        or value != value.strip()
    ):
        raise SalesFulfillmentError(
            f"{field} must contain 1 to {max_length} trimmed characters."
        )


__all__ = [
    "SalesFulfillmentError",
    "SalesShipment",
    "SalesShipmentStatus",
    "ShippingLabel",
]

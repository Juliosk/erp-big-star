"""Pure lifecycle coverage for multichannel sales shipments."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from erp.modules.sales.domain import (
    Marketplace,
    SalesFulfillmentError,
    SalesShipment,
    SalesShipmentStatus,
    ShippingLabel,
)


def _label() -> ShippingLabel:
    return ShippingLabel("CHANNEL", "STANDARD", "TRK213", "label://shopee/213")


def _shipment() -> SalesShipment:
    return SalesShipment.create(
        company_id=uuid4(),
        sales_order_id=uuid4(),
        wms_shipment_id=uuid4(),
        channel_config_id=uuid4(),
        account_id=uuid4(),
        marketplace=Marketplace.SHOPEE,
        external_order_id="SHOPEE-213",
        label=_label(),
    )


def test_labeled_shipment_dispatches_as_new_immutable_version() -> None:
    labeled = _shipment()
    now = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
    dispatched = labeled.dispatch(now=now)

    assert labeled.status is SalesShipmentStatus.LABEL_CREATED
    assert labeled.version == 1
    assert dispatched.status is SalesShipmentStatus.DISPATCHED
    assert dispatched.dispatched_at == now
    assert dispatched.version == 2
    with pytest.raises(FrozenInstanceError):
        dispatched.version = 3  # type: ignore[misc]


def test_dispatch_is_not_repeatable_and_requires_aware_timestamp() -> None:
    labeled = _shipment()
    with pytest.raises(SalesFulfillmentError, match="timezone-aware"):
        labeled.dispatch(now=datetime(2026, 11, 10))  # noqa: DTZ001
    with pytest.raises(SalesFulfillmentError, match="Only a labeled"):
        labeled.dispatch().dispatch()


@pytest.mark.parametrize(
    "label",
    [
        ShippingLabel("CHANNEL", "STANDARD", "TRK213", "label://valid"),
    ],
)
def test_direct_state_snapshots_enforce_dispatch_timestamp(label: ShippingLabel) -> None:
    labeled = _shipment()
    with pytest.raises(SalesFulfillmentError, match="requires a timestamp"):
        replace(labeled, status=SalesShipmentStatus.DISPATCHED, label=label)
    with pytest.raises(SalesFulfillmentError, match="cannot be dispatched"):
        replace(labeled, dispatched_at=datetime.now(UTC), label=label)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("carrier_code", ""),
        ("service_code", " STANDARD"),
        ("tracking_code", "X" * 81),
        ("label_reference", ""),
    ],
)
def test_shipping_label_rejects_invalid_fields(field: str, value: str) -> None:
    values = {
        "carrier_code": "CHANNEL",
        "service_code": "STANDARD",
        "tracking_code": "TRK213",
        "label_reference": "label://valid",
    }
    values[field] = value
    with pytest.raises(SalesFulfillmentError):
        ShippingLabel(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("marketplace", "UNKNOWN", "marketplace"),
        ("status", "UNKNOWN", "status"),
        ("label", None, "label"),
        ("version", 0, "version"),
        ("id", UUID(int=0), "identities"),
    ],
)
def test_shipment_rejects_invalid_direct_snapshots(
    field: str, value: Any, message: str
) -> None:
    with pytest.raises(SalesFulfillmentError, match=message):
        replace(_shipment(), **{field: value})


def test_shipment_rejects_naive_persisted_dispatch_timestamp() -> None:
    with pytest.raises(SalesFulfillmentError, match="timezone-aware"):
        replace(
            _shipment(),
            dispatched_at=datetime(2026, 11, 10),  # noqa: DTZ001
        )


def test_shipping_label_rejects_non_string_value() -> None:
    with pytest.raises(SalesFulfillmentError):
        ShippingLabel(None, "STANDARD", "TRK213", "label://valid")  # type: ignore[arg-type]


__all__: list[str] = []

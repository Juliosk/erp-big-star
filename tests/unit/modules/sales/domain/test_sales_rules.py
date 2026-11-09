"""Pure multichannel order, monetary and scope invariants."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.sales.domain.channels import (
    ChannelMarginAnalysis,
    ChannelOrderItem,
    ChannelOrderReference,
    ChannelOrderSnapshot,
    ChannelOrderStatus,
    ChannelSkuMapping,
    ChannelSkuMappingEntry,
    Marketplace,
    MultichannelSalesOrder,
    SalesChannelAccount,
    SalesChannelError,
    SalesChannelVersionConflictError,
    channel_order_fingerprint,
)

D = Decimal


def invalid_replace(value: object, **changes: object) -> object:
    # Intentionally malformed constructor inputs exercise runtime validation.
    return replace(cast(Any, value), **changes)


def snapshot(marketplace: Marketplace = Marketplace.SHOPEE) -> ChannelOrderSnapshot:
    reference = ChannelOrderReference(uuid4(), uuid4(), marketplace, "Order-aB01")
    mapping = ChannelSkuMapping(
        reference.company_id,
        reference.account_id,
        marketplace,
        "Listing-01",
        "Variant-01",
        "Sku-aB",
        uuid4(),
    )
    return ChannelOrderSnapshot(
        reference,
        ChannelOrderStatus.PENDING,
        (ChannelOrderItem("line-1", mapping, D("2"), D("10.00"), D("1.00")),),
        D("5.00"),
        D("2.00"),
    )


@pytest.mark.parametrize("marketplace", tuple(Marketplace))
def test_channels_preserve_identity_totals_and_immutable_state(marketplace: Marketplace) -> None:
    order = snapshot(marketplace)
    assert order.reference.external_order_id == "Order-aB01"
    assert order.items[0].mapping.external_sku == "Sku-aB"
    assert order.reference.ingestion_key == (
        order.reference.company_id,
        marketplace,
        order.reference.account_id,
        "Order-aB01",
    )
    assert order.items[0].gross_amount == D("20")
    assert order.merchandise_amount == D("19")
    assert order.total_amount == D("22")
    paid = order.transition(ChannelOrderStatus.PAID)
    assert paid.transition(ChannelOrderStatus.SHIPPED).status is ChannelOrderStatus.SHIPPED
    assert paid.transition(ChannelOrderStatus.CANCELLED).status is ChannelOrderStatus.CANCELLED
    assert order.transition(ChannelOrderStatus.CANCELLED).status is ChannelOrderStatus.CANCELLED
    assert order.status is ChannelOrderStatus.PENDING
    with pytest.raises(FrozenInstanceError):
        cast(Any, order).currency = "USD"


@pytest.mark.parametrize("source", tuple(ChannelOrderStatus))
@pytest.mark.parametrize("target", tuple(ChannelOrderStatus))
def test_status_matrix_never_regresses(
    source: ChannelOrderStatus, target: ChannelOrderStatus
) -> None:
    order = replace(snapshot(), status=source)
    permitted = {
        (ChannelOrderStatus.PENDING, ChannelOrderStatus.PAID),
        (ChannelOrderStatus.PENDING, ChannelOrderStatus.CANCELLED),
        (ChannelOrderStatus.PAID, ChannelOrderStatus.SHIPPED),
        (ChannelOrderStatus.PAID, ChannelOrderStatus.CANCELLED),
    }
    if (source, target) in permitted:
        assert order.transition(target).status is target
    else:
        with pytest.raises(SalesChannelError):
            order.transition(target)


@pytest.mark.parametrize("field", ["company_id", "account_id", "marketplace"])
def test_mapping_cannot_cross_tenant_account_or_channel(field: str) -> None:
    order = snapshot()
    value = Marketplace.NUVEMSHOP if field == "marketplace" else uuid4()
    reference = invalid_replace(order.reference, **{field: value})
    with pytest.raises(SalesChannelError):
        invalid_replace(order, reference=reference)


@pytest.mark.parametrize(
    "value", [D("NaN"), D("Infinity"), D("-1"), D("0"), D("0.0000001"), D("1000000000000"), 1.0]
)
def test_invalid_quantities_are_rejected(value: Decimal) -> None:
    with pytest.raises(SalesChannelError):
        replace(snapshot().items[0], quantity=value)


@pytest.mark.parametrize("field", ["unit_price", "discount_amount"])
def test_item_rejects_fractional_cents(field: str) -> None:
    with pytest.raises(SalesChannelError):
        invalid_replace(snapshot().items[0], **{field: D("1.001")})


def test_rounding_discounts_freight_and_repeated_products() -> None:
    order = snapshot()
    item = replace(order.items[0], quantity=D("0.5"), unit_price=D("0.01"), discount_amount=D("0"))
    assert item.gross_amount == D("0.01")
    repeated = replace(order.items[0], external_item_id="line-2")
    assert replace(order, items=(*order.items, repeated)).total_amount == D("41")
    assert replace(order, discount_amount=D("19")).total_amount == D("5")
    with pytest.raises(SalesChannelError):
        replace(order.items[0], discount_amount=D("21"))
    with pytest.raises(SalesChannelError):
        replace(order, discount_amount=D("20"))
    with pytest.raises(SalesChannelError):
        replace(order, items=(*order.items, order.items[0]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reference", None),
        ("status", "unknown"),
        ("items", ()),
        ("items", []),
        ("items", (None,)),
        ("currency", "USD"),
        ("freight_amount", D("-1")),
        ("discount_amount", D("NaN")),
    ],
)
def test_order_constructor_enforces_invariants(field: str, value: object) -> None:
    with pytest.raises(SalesChannelError):
        invalid_replace(snapshot(), **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", UUID(int=0)),
        ("account_id", None),
        ("marketplace", "unknown"),
        ("external_order_id", ""),
        ("external_order_id", " spaced "),
        ("external_order_id", "a" * 129),
    ],
)
def test_invalid_reference(field: str, value: object) -> None:
    with pytest.raises(SalesChannelError):
        invalid_replace(snapshot().reference, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"), [("variation_id", ""), ("external_sku", ""), ("product_id", UUID(int=0))]
)
def test_invalid_mapping(field: str, value: object) -> None:
    with pytest.raises(SalesChannelError):
        invalid_replace(snapshot().items[0].mapping, **{field: value})


def test_item_requires_explicit_mapping() -> None:
    with pytest.raises(SalesChannelError):
        invalid_replace(snapshot().items[0], mapping=None)


def test_margin_recalculates_after_discount_fees_and_freight() -> None:
    analysis = ChannelMarginAnalysis(D("100"), D("60"), D("10"), D("5"))
    assert analysis.contribution_amount == D("25")
    assert analysis.margin_ratio == D("0.25")
    assert analysis.meets(D("0.25"))
    assert not replace(analysis, revenue=D("90")).meets(D("0.25"))
    assert replace(analysis, product_cost=D("120")).margin_ratio == D("-0.35")
    assert ChannelMarginAnalysis(D("1"), D("0")).meets(D("0.999999"))
    with pytest.raises(SalesChannelError):
        analysis.meets(D("1"))
    with pytest.raises(SalesChannelError):
        ChannelMarginAnalysis(D("0"), D("0"))


def test_channel_persistence_records_are_immutable_and_versioned() -> None:
    order = snapshot()
    account = SalesChannelAccount.create(
        company_id=order.reference.company_id,
        account_id=order.reference.account_id,
        marketplace=order.reference.marketplace,
        display_name="Shopee principal",
        credential_reference="secret://sales/shopee/principal",
    )
    mapping = ChannelSkuMappingEntry.create(
        channel_config_id=account.id,
        mapping=order.items[0].mapping,
    )
    captured = MultichannelSalesOrder.capture(
        channel_config_id=account.id,
        snapshot=order,
    )
    assert len(channel_order_fingerprint(order)) == 64
    assert account.set_active(False).record_version == 2
    assert mapping.remap(uuid4()).record_version == 2
    assert captured.revise(order.transition(ChannelOrderStatus.PAID)).record_version == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("marketplace", "UNKNOWN"),
        ("credential_reference", ""),
        ("credential_reference", " spaced "),
        ("credential_reference", "x" * 256),
        ("active", 1),
        ("record_version", 0),
    ],
)
def test_invalid_channel_account_record(field: str, value: object) -> None:
    order = snapshot()
    account = SalesChannelAccount.create(
        company_id=order.reference.company_id,
        account_id=order.reference.account_id,
        marketplace=order.reference.marketplace,
        display_name="Shopee principal",
        credential_reference="secret://sales/shopee/principal",
    )
    with pytest.raises(SalesChannelError):
        invalid_replace(account, **{field: value})


@pytest.mark.parametrize("active", [True, 1])
def test_channel_account_state_requires_a_real_change(active: object) -> None:
    order = snapshot()
    account = SalesChannelAccount.create(
        company_id=order.reference.company_id,
        account_id=order.reference.account_id,
        marketplace=order.reference.marketplace,
        display_name="Shopee principal",
        credential_reference="secret://sales/shopee/principal",
    )
    with pytest.raises(SalesChannelError):
        account.set_active(cast(Any, active))


@pytest.mark.parametrize(
    ("field", "value"),
    [("mapping", None), ("active", 1), ("record_version", 0)],
)
def test_invalid_sku_mapping_record(field: str, value: object) -> None:
    order = snapshot()
    entry = ChannelSkuMappingEntry.create(
        channel_config_id=uuid4(), mapping=order.items[0].mapping
    )
    with pytest.raises(SalesChannelError):
        invalid_replace(entry, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot", None),
        ("source_fingerprint", "INVALID"),
        ("source_fingerprint", "g" * 64),
        ("record_version", 0),
    ],
)
def test_invalid_multichannel_order_record(field: str, value: object) -> None:
    order = MultichannelSalesOrder.capture(
        channel_config_id=uuid4(), snapshot=snapshot()
    )
    with pytest.raises(SalesChannelError):
        invalid_replace(order, **{field: value})


def test_fingerprint_and_revision_require_canonical_snapshot_identity() -> None:
    order = snapshot()
    captured = MultichannelSalesOrder.capture(
        channel_config_id=uuid4(), snapshot=order
    )
    with pytest.raises(SalesChannelError):
        channel_order_fingerprint(cast(Any, None))
    with pytest.raises(SalesChannelError):
        captured.revise(replace(order, reference=replace(order.reference, external_order_id="NEW")))

    conflict = SalesChannelVersionConflictError(4)
    assert conflict.expected_version == 4
    assert conflict.code == "VERSION_CONFLICT"

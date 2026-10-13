"""Pure M6 three-way matching tolerance and combination rules."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.procurement.domain import (
    InvalidMatchingLineError,
    InvalidMatchingToleranceError,
    MatchingScopeError,
    MatchingTolerancePolicy,
    MatchStatus,
    ThreeWayMatchLine,
    ThreeWayMatchReferences,
    compare_line,
    compare_lines,
)


def policy(
    *,
    company_id: UUID | None = None,
    price: str = "1",
    quantity: str = "2",
    rounding: str = "0.01",
) -> MatchingTolerancePolicy:
    return MatchingTolerancePolicy.create(
        company_id=company_id or uuid4(),
        unit_price_variance_percentage=price,
        quantity_variance_percentage=quantity,
        rounding_absolute_limit=rounding,
        version=2,
    )


def line(
    *,
    company_id: UUID,
    key: str = "SKU-001",
    received: str = "10",
    invoiced: str = "10",
    ordered_price: str = "100",
    invoiced_price: str = "100",
) -> ThreeWayMatchLine:
    return ThreeWayMatchLine.create(
        company_id=company_id,
        match_key=key,
        purchase_order_item_id=uuid4(),
        goods_receipt_item_id=uuid4(),
        fiscal_document_item_id=uuid4(),
        ordered_quantity="10",
        received_quantity=received,
        invoiced_quantity=invoiced,
        ordered_unit_price=ordered_price,
        invoiced_unit_price=invoiced_price,
        currency="brl",
    )


def test_exact_and_boundary_values_are_matched_and_immutable() -> None:
    configured = policy()
    compared = line(
        company_id=configured.company_id,
        received="10.2",
        invoiced_price="101",
    )
    result = compare_line(compared, configured)

    assert result.status is MatchStatus.MATCHED
    assert result.reasons == ()
    assert result.quantity_delta == Decimal("0.200000")
    assert result.unit_price_delta == Decimal("1.000000")
    assert result.allowed_quantity_delta == Decimal("0.2000000000")
    assert result.allowed_unit_price_delta == Decimal("1.0000000000")
    assert compared.match_key == "SKU-001"
    assert compared.currency == "BRL"
    assert configured.version == 2
    with pytest.raises(FrozenInstanceError):
        configured.version = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    ("received", "invoice_price", "expected", "reasons"),
    [
        ("10.200001", "101", MatchStatus.QUANTITY_MISMATCH, ("QUANTITY_TOLERANCE_EXCEEDED",)),
        ("10.2", "101.000001", MatchStatus.PRICE_MISMATCH, ("UNIT_PRICE_TOLERANCE_EXCEEDED",)),
        (
            "10.200001",
            "101.000001",
            MatchStatus.TOLERANCE_EXCEEDED,
            ("QUANTITY_TOLERANCE_EXCEEDED", "UNIT_PRICE_TOLERANCE_EXCEEDED"),
        ),
    ],
)
def test_line_statuses_explain_each_tolerance_failure(
    received: str,
    invoice_price: str,
    expected: MatchStatus,
    reasons: tuple[str, ...],
) -> None:
    configured = policy()
    result = compare_line(
        line(
            company_id=configured.company_id,
            received=received,
            invoiced_price=invoice_price,
        ),
        configured,
    )
    assert result.status is expected
    assert result.reasons == reasons


def test_absolute_rounding_limit_is_used_when_percentage_is_lower() -> None:
    configured = policy(price="0", quantity="0", rounding="0.01")
    accepted = compare_line(
        line(company_id=configured.company_id, invoiced_price="100.01"), configured
    )
    rejected = compare_line(
        line(company_id=configured.company_id, invoiced_price="100.010001"), configured
    )
    assert accepted.status is MatchStatus.MATCHED
    assert accepted.allowed_unit_price_delta == Decimal("0.01")
    assert rejected.status is MatchStatus.PRICE_MISMATCH


def test_report_combines_lines_with_deterministic_precedence() -> None:
    configured = policy()
    exact = line(company_id=configured.company_id, key="SKU-A")
    quantity_mismatch = line(company_id=configured.company_id, key="SKU-B", received="11")
    price_mismatch = line(company_id=configured.company_id, key="SKU-C", invoiced_price="105")

    matched = compare_lines((exact,), configured)
    quantity = compare_lines((exact, quantity_mismatch), configured)
    price = compare_lines((exact, price_mismatch), configured)
    combined = compare_lines((quantity_mismatch, price_mismatch), configured)

    assert matched.matched
    assert matched.status is MatchStatus.MATCHED
    assert quantity.status is MatchStatus.QUANTITY_MISMATCH
    assert price.status is MatchStatus.PRICE_MISMATCH
    assert combined.status is MatchStatus.TOLERANCE_EXCEEDED
    assert not combined.matched
    assert combined.company_id == configured.company_id
    assert combined.policy is configured


def test_report_preserves_tolerance_exceeded_from_one_line() -> None:
    configured = policy()
    result = compare_lines(
        (
            line(
                company_id=configured.company_id,
                received="11",
                invoiced_price="105",
            ),
        ),
        configured,
    )
    assert result.status is MatchStatus.TOLERANCE_EXCEEDED


def test_references_are_tenant_bound_immutable_identifiers() -> None:
    company_id = uuid4()
    receipts = (uuid4(), uuid4())
    fiscal_documents = (uuid4(),)
    references = ThreeWayMatchReferences.create(
        company_id=company_id,
        purchase_order_id=uuid4(),
        goods_receipt_ids=receipts,
        inbound_fiscal_document_ids=fiscal_documents,
        provisional_entry_id=uuid4(),
        payable_id=uuid4(),
    )
    assert references.company_id == company_id
    assert references.goods_receipt_ids == receipts
    assert references.inbound_fiscal_document_ids == fiscal_documents
    assert references.payable_id is not None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("unit_price_variance_percentage", "-0.0001", "between 0 and 100"),
        ("quantity_variance_percentage", "100.0001", "between 0 and 100"),
        ("unit_price_variance_percentage", "NaN", "finite"),
        ("quantity_variance_percentage", "bad", "valid decimal"),
        ("unit_price_variance_percentage", "1E+999999", "valid decimal"),
        ("rounding_absolute_limit", "1.01", "between 0.00 and 1.00"),
        ("rounding_absolute_limit", "Infinity", "finite"),
    ],
)
def test_policy_rejects_invalid_tolerances(field: str, value: str, message: str) -> None:
    kwargs = {field: value}
    with pytest.raises(InvalidMatchingToleranceError, match=message):
        MatchingTolerancePolicy.create(company_id=uuid4(), **kwargs)  # type: ignore[arg-type]


def test_policy_rejects_invalid_identity_version_and_contract() -> None:
    with pytest.raises(InvalidMatchingToleranceError, match="company_id"):
        MatchingTolerancePolicy.create(company_id=cast(UUID, "invalid"))
    with pytest.raises(InvalidMatchingToleranceError, match="version"):
        MatchingTolerancePolicy.create(company_id=uuid4(), version=0)
    with pytest.raises(InvalidMatchingToleranceError, match="version"):
        MatchingTolerancePolicy.create(company_id=uuid4(), version=cast(int, True))
    with pytest.raises(InvalidMatchingToleranceError, match="policy"):
        compare_line(line(company_id=uuid4()), cast(MatchingTolerancePolicy, "invalid"))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ordered_quantity", "0", "positive"),
        ("invoiced_quantity", "-1", "positive"),
        ("received_quantity", "-0.000001", "negative"),
        ("ordered_unit_price", "-0.000001", "negative"),
        ("invoiced_unit_price", "NaN", "finite"),
        ("received_quantity", "bad", "valid decimal"),
    ],
)
def test_line_rejects_invalid_decimal_invariants(field: str, value: str, message: str) -> None:
    configured = policy()
    valid = line(company_id=configured.company_id)
    with pytest.raises(InvalidMatchingLineError, match=message):
        replace(valid, **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("company_id", "invalid", "company_id"),
        ("purchase_order_item_id", "invalid", "purchase_order_item_id"),
        ("goods_receipt_item_id", "invalid", "goods_receipt_item_id"),
        ("fiscal_document_item_id", "invalid", "fiscal_document_item_id"),
        ("match_key", "invalid key", "canonical"),
        ("match_key", 1, "text"),
        ("currency", "REAL", "ISO 4217"),
        ("currency", 1, "ISO 4217"),
    ],
)
def test_line_rejects_invalid_boundary_values(field: str, value: object, message: str) -> None:
    valid = line(company_id=uuid4())
    with pytest.raises(InvalidMatchingLineError, match=message):
        replace(valid, **{field: value})  # type: ignore[arg-type]


def test_comparison_rejects_wrong_type_cross_tenant_and_invalid_sets() -> None:
    configured = policy()
    valid = line(company_id=configured.company_id)
    with pytest.raises(InvalidMatchingLineError, match="ThreeWayMatchLine"):
        compare_line(cast(ThreeWayMatchLine, "invalid"), configured)
    with pytest.raises(MatchingScopeError, match="same company"):
        compare_line(replace(valid, company_id=uuid4()), configured)
    with pytest.raises(InvalidMatchingLineError, match="non-empty tuple"):
        compare_lines((), configured)
    with pytest.raises(InvalidMatchingLineError, match="non-empty tuple"):
        compare_lines(cast(tuple[ThreeWayMatchLine, ...], [valid]), configured)
    with pytest.raises(InvalidMatchingLineError, match="every line"):
        compare_lines((cast(ThreeWayMatchLine, "invalid"),), configured)
    with pytest.raises(InvalidMatchingLineError, match="unique"):
        compare_lines((valid, replace(valid, purchase_order_item_id=uuid4())), configured)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("company_id", "invalid", "company_id"),
        ("purchase_order_id", "invalid", "purchase_order_id"),
        ("provisional_entry_id", "invalid", "provisional_entry_id"),
        ("payable_id", "invalid", "payable_id"),
        ("goods_receipt_ids", (), "non-empty tuple"),
        ("goods_receipt_ids", [uuid4()], "non-empty tuple"),
        ("goods_receipt_ids", ("invalid",), "member must be a UUID"),
        ("inbound_fiscal_document_ids", (), "non-empty tuple"),
    ],
)
def test_references_reject_invalid_contracts(field: str, value: object, message: str) -> None:
    valid = ThreeWayMatchReferences.create(
        company_id=uuid4(),
        purchase_order_id=uuid4(),
        goods_receipt_ids=(uuid4(),),
        inbound_fiscal_document_ids=(uuid4(),),
        provisional_entry_id=uuid4(),
    )
    with pytest.raises(InvalidMatchingLineError, match=message):
        replace(valid, **{field: value})  # type: ignore[arg-type]


def test_references_reject_duplicate_source_ids() -> None:
    duplicate = uuid4()
    with pytest.raises(InvalidMatchingLineError, match="unique"):
        ThreeWayMatchReferences.create(
            company_id=uuid4(),
            purchase_order_id=uuid4(),
            goods_receipt_ids=(duplicate, duplicate),
            inbound_fiscal_document_ids=(uuid4(),),
            provisional_entry_id=uuid4(),
        )

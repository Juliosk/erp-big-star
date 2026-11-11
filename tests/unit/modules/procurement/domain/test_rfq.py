"""Branch-complete tests for the pure M6 RFQ aggregate."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from erp.modules.procurement.domain import (
    InvalidRequestForQuotationError,
    InvalidRequestForQuotationTransitionError,
    ProcurementDomainError,
    QuotationAward,
    RequestForQuotation,
    RequestForQuotationItem,
    RequestForQuotationStatus,
    SupplierQuote,
    SupplierQuoteLine,
)

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
TODAY = date(2026, 11, 11)


def _item(**changes: Any) -> RequestForQuotationItem:
    values: dict[str, Any] = {
        "id": uuid4(),
        "product_id": uuid4(),
        "quantity": Decimal("10"),
        "uom": " un ",
        "required_on": date(2026, 12, 1),
        "specification": " Brinquedo certificado ",
    }
    values.update(changes)
    return RequestForQuotationItem(**values)


def _quote(
    item: RequestForQuotationItem,
    *,
    supplier_id: object | None = None,
    **changes: Any,
) -> SupplierQuote:
    values: dict[str, Any] = {
        "id": uuid4(),
        "supplier_id": supplier_id or uuid4(),
        "currency": "brl",
        "submitted_at": NOW + timedelta(hours=1),
        "valid_until": date(2026, 12, 15),
        "lines": (
            SupplierQuoteLine(
                rfq_item_id=item.id,
                offered_quantity=item.quantity,
                unit_price=Decimal("12.50"),
                lead_time_days=5,
            ),
        ),
        "freight_amount": Decimal("20"),
    }
    values.update(changes)
    return SupplierQuote(**values)


def _rfq(**changes: Any) -> RequestForQuotation:
    item = changes.pop("item", _item())
    supplier_id = changes.pop("supplier_id", uuid4())
    values: dict[str, Any] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "code": " rfq-2026-001 ",
        "created_by": uuid4(),
        "response_deadline": date(2026, 11, 30),
        "items": (item,),
        "invited_supplier_ids": (supplier_id,),
    }
    values.update(changes)
    return RequestForQuotation(**values)


def test_rfq_happy_path_is_immutable_complete_and_versioned() -> None:
    item = _item()
    supplier_id = uuid4()
    draft = _rfq(item=item, supplier_id=supplier_id)
    quote = _quote(item, supplier_id=supplier_id)

    assert draft.code == "RFQ-2026-001"
    assert item.uom == "UN"
    assert item.specification == "Brinquedo certificado"
    assert quote.currency == "BRL"
    assert quote.lines[0].line_total == Decimal("125.00")
    assert quote.total_amount == Decimal("145.00")
    with pytest.raises(FrozenInstanceError):
        draft.code = "CHANGED"  # type: ignore[misc]

    opened = draft.open(occurred_at=NOW)
    quoted = opened.record_quote(quote)
    closed = quoted.close(occurred_at=NOW + timedelta(days=1))
    awarded = closed.award_quote(
        quote_id=quote.id,
        actor_id=uuid4(),
        occurred_at=NOW + timedelta(days=2),
    )

    assert awarded.status is RequestForQuotationStatus.AWARDED
    assert awarded.award is not None
    assert awarded.award.supplier_id == supplier_id
    assert awarded.version == 5
    assert draft.status is RequestForQuotationStatus.DRAFT


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "bad"}, "UUID"),
        ({"product_id": "bad"}, "UUID"),
        ({"quantity": 0}, "positive"),
        ({"uom": "bad unit"}, "canonical identifier"),
        ({"required_on": "2026-12-01"}, "must be a date"),
        ({"specification": ""}, "must contain"),
    ],
)
def test_rfq_item_rejects_invalid_values(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ProcurementDomainError, match=message):
        _item(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"rfq_item_id": "bad"}, "UUID"),
        ({"offered_quantity": 0}, "positive"),
        ({"unit_price": Decimal("0")}, "unit_price must be positive"),
        ({"lead_time_days": True}, "non-negative integer"),
        ({"lead_time_days": -1}, "non-negative integer"),
    ],
)
def test_supplier_quote_line_rejects_invalid_values(
    changes: dict[str, Any], message: str
) -> None:
    values: dict[str, Any] = {
        "rfq_item_id": uuid4(),
        "offered_quantity": Decimal("1"),
        "unit_price": Decimal("1"),
        "lead_time_days": 0,
    }
    values.update(changes)
    with pytest.raises(ProcurementDomainError, match=message):
        SupplierQuoteLine(**values)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "bad"}, "UUID"),
        ({"currency": "REAL"}, "ISO 4217"),
        ({"submitted_at": NOW.replace(tzinfo=None)}, "timezone-aware"),
        ({"valid_until": date(2026, 1, 1)}, "cannot predate"),
        ({"lines": ()}, "must contain lines"),
        ({"lines": (object(),)}, "SupplierQuoteLine"),
        ({"freight_amount": Decimal("-1")}, "cannot be negative"),
    ],
)
def test_supplier_quote_rejects_invalid_values(changes: dict[str, Any], message: str) -> None:
    item = _item()
    with pytest.raises(ProcurementDomainError, match=message):
        _quote(item, **changes)


def test_supplier_quote_rejects_duplicate_items() -> None:
    item = _item()
    line = SupplierQuoteLine(item.id, Decimal("10"), Decimal("1"), 0)

    with pytest.raises(InvalidRequestForQuotationError, match="cannot repeat"):
        _quote(item, lines=(line, line))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "bad"}, "UUID"),
        ({"response_deadline": "2026-11-30"}, "must be a date"),
        ({"items": ()}, "must contain items"),
        ({"items": (object(),)}, "RFQ items"),
        ({"invited_supplier_ids": ()}, "at least one supplier"),
        ({"invited_supplier_ids": ("bad",)}, "UUID"),
        ({"status": "DRAFT"}, "RFQ status"),
        ({"version": False}, "positive integer"),
    ],
)
def test_rfq_rejects_invalid_root_values(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ProcurementDomainError, match=message):
        _rfq(**changes)


def test_rfq_rejects_duplicate_items_and_suppliers() -> None:
    item = _item()
    supplier_id = uuid4()

    with pytest.raises(InvalidRequestForQuotationError, match="identities"):
        _rfq(items=(item, item))
    with pytest.raises(InvalidRequestForQuotationError, match="must be unique"):
        _rfq(invited_supplier_ids=(supplier_id, supplier_id))


def test_rfq_quote_validation_is_fail_closed() -> None:
    item = _item()
    supplier_id = uuid4()
    opened = _rfq(item=item, supplier_id=supplier_id).open(occurred_at=NOW)

    with pytest.raises(InvalidRequestForQuotationError, match="SupplierQuote"):
        opened.record_quote(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidRequestForQuotationError, match="not invited"):
        opened.record_quote(_quote(item))
    with pytest.raises(InvalidRequestForQuotationError, match="after the deadline"):
        opened.record_quote(
            _quote(
                item,
                supplier_id=supplier_id,
                submitted_at=datetime(2026, 12, 1, tzinfo=UTC),
            )
        )
    with pytest.raises(InvalidRequestForQuotationError, match="cover every"):
        opened.record_quote(
            _quote(item, supplier_id=supplier_id, lines=(
                SupplierQuoteLine(uuid4(), Decimal("10"), Decimal("1"), 0),
            ))
        )
    with pytest.raises(InvalidRequestForQuotationError, match="less than requested"):
        opened.record_quote(
            _quote(item, supplier_id=supplier_id, lines=(
                SupplierQuoteLine(item.id, Decimal("9"), Decimal("1"), 0),
            ))
        )

    quoted = opened.record_quote(_quote(item, supplier_id=supplier_id))
    with pytest.raises(InvalidRequestForQuotationError, match="already submitted"):
        quoted.record_quote(_quote(item, supplier_id=supplier_id))


def test_rfq_transitions_validate_state_time_and_award_authority() -> None:
    item = _item()
    supplier_id = uuid4()
    draft = _rfq(item=item, supplier_id=supplier_id)

    with pytest.raises(InvalidRequestForQuotationTransitionError):
        draft.close(occurred_at=NOW)
    with pytest.raises(InvalidRequestForQuotationError, match="timezone-aware"):
        draft.open(occurred_at=NOW.replace(tzinfo=None))

    opened = draft.open(occurred_at=NOW)
    with pytest.raises(InvalidRequestForQuotationError, match="without supplier quotes"):
        opened.close(occurred_at=NOW)
    quote = _quote(item, supplier_id=supplier_id)
    quoted = opened.record_quote(quote)
    with pytest.raises(InvalidRequestForQuotationError, match="predate opened_at"):
        quoted.close(occurred_at=NOW - timedelta(seconds=1))
    closed = quoted.close(occurred_at=NOW + timedelta(hours=2))

    with pytest.raises(InvalidRequestForQuotationError, match="creator cannot award"):
        closed.award_quote(quote_id=quote.id, actor_id=draft.created_by, occurred_at=NOW)
    with pytest.raises(InvalidRequestForQuotationError, match="does not exist"):
        closed.award_quote(quote_id=uuid4(), actor_id=uuid4(), occurred_at=NOW)
    expired_quote = replace(quote, valid_until=TODAY)
    expired_closed = replace(closed, supplier_quotes=(expired_quote,))
    with pytest.raises(InvalidRequestForQuotationError, match="expired"):
        expired_closed.award_quote(
            quote_id=expired_quote.id,
            actor_id=uuid4(),
            occurred_at=NOW + timedelta(days=1),
        )
    with pytest.raises(InvalidRequestForQuotationError, match="timezone-aware"):
        closed.award_quote(
            quote_id=quote.id,
            actor_id=uuid4(),
            occurred_at=NOW.replace(tzinfo=None),
        )


def test_rfq_cancellation_is_normalized_and_terminal() -> None:
    cancelled = _rfq().cancel(reason="  fornecedor indisponível  ")

    assert cancelled.status is RequestForQuotationStatus.CANCELLED
    assert cancelled.cancellation_reason == "fornecedor indisponível"
    with pytest.raises(InvalidRequestForQuotationTransitionError):
        cancelled.cancel(reason="again")


def test_rfq_rehydration_rejects_incoherent_evidence() -> None:
    item = _item()
    supplier_id = uuid4()
    draft = _rfq(item=item, supplier_id=supplier_id)
    quote = _quote(item, supplier_id=supplier_id)
    opened = draft.open(occurred_at=NOW)
    quoted = opened.record_quote(quote)
    closed = quoted.close(occurred_at=NOW + timedelta(hours=2))
    award = QuotationAward(quote.id, supplier_id, uuid4(), NOW + timedelta(hours=3))

    invalid: list[tuple[RequestForQuotation, dict[str, Any]]] = [
        (draft, {"opened_at": NOW}),
        (opened, {"opened_at": NOW.replace(tzinfo=None)}),
        (opened, {"supplier_quotes": (object(),)}),
        (opened, {"supplier_quotes": (quote, quote)}),
        (opened, {"opened_at": None}),
        (closed, {"closed_at": None}),
        (closed, {"closed_at": NOW - timedelta(seconds=1)}),
        (closed, {"award": award}),
        (closed, {"status": RequestForQuotationStatus.AWARDED, "award": object()}),
        (
            closed,
            {
                "status": RequestForQuotationStatus.AWARDED,
                "award": replace(award, quote_id=uuid4()),
            },
        ),
        (
            closed,
            {
                "status": RequestForQuotationStatus.AWARDED,
                "award": replace(award, supplier_id=uuid4()),
            },
        ),
        (
            closed,
            {
                "status": RequestForQuotationStatus.AWARDED,
                "award": replace(award, awarded_at=NOW),
            },
        ),
        (draft, {"status": RequestForQuotationStatus.CANCELLED}),
        (draft, {"cancellation_reason": "reason"}),
    ]

    for source, changes in invalid:
        with pytest.raises(InvalidRequestForQuotationError):
            replace(source, **changes)


def test_award_value_object_rejects_bad_identity_and_timestamp() -> None:
    with pytest.raises(ProcurementDomainError, match="UUID"):
        QuotationAward("bad", uuid4(), uuid4(), NOW)  # type: ignore[arg-type]
    with pytest.raises(InvalidRequestForQuotationError, match="timezone-aware"):
        QuotationAward(uuid4(), uuid4(), uuid4(), NOW.replace(tzinfo=None))

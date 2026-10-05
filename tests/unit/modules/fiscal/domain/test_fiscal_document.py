"""FiscalDocument pure aggregate invariants and lifecycle."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentItem,
    FiscalDocumentModel,
    FiscalDocumentStatus,
    FiscalDocumentTotals,
    FiscalDomainError,
    FiscalPartySnapshot,
    ImmutableDocumentError,
    InvalidStateTransitionError,
    NFeAccessKey,
    SefazResponseSnapshot,
    TaxComponentSnapshot,
    TaxKind,
    TaxMismatchError,
    TaxSnapshot,
)


def access_key(model: str = "55") -> NFeAccessKey:
    body = f"35" "2610" "12345678000195" f"{model}" "001" "000000123" "1" "12345678"
    weight = 2
    total = 0
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return NFeAccessKey(body + str(0 if remainder in {0, 1} else 11 - remainder))


def taxes() -> TaxSnapshot:
    def component(kind: TaxKind, amount: str) -> TaxComponentSnapshot:
        return TaxComponentSnapshot.create(
            kind=kind,
            tax_code="00",
            taxable_base="20",
            rate="1",
            amount=amount,
        )

    return TaxSnapshot(
        icms=component(TaxKind.ICMS, "1"),
        pis=component(TaxKind.PIS, "0.10"),
        cofins=component(TaxKind.COFINS, "0.20"),
        ipi=component(TaxKind.IPI, "0.30"),
    )


def party(tax_id: str = "12345678000195") -> FiscalPartySnapshot:
    return FiscalPartySnapshot(
        tax_id=tax_id,
        legal_name="  Big Star Brinquedos  ",
        state_registration="123",
        street="Rua Fiscal",
        number="100",
        district="Centro",
        city="São Paulo",
        state_code="sp",
        postal_code="01.001-000",
    )


def item(*, total: str | None = None, item_id: UUID | None = None) -> FiscalDocumentItem:
    return FiscalDocumentItem.create(
        item_id=item_id,
        product_id=uuid4(),
        code=" SKU-1 ",
        description=" Produto fiscal ",
        ncm="95030099",
        cfop="5102",
        unit_of_measure="un",
        quantity="2",
        unit_price="10",
        freight_amount="1",
        discount_amount="2",
        total_amount=total,
        tax_snapshot=taxes(),
    )


def draft(
    *,
    items: tuple[FiscalDocumentItem, ...] | None = None,
    totals: FiscalDocumentTotals | None = None,
    model: FiscalDocumentModel = FiscalDocumentModel.NFE,
) -> FiscalDocument:
    lines = tuple(items or (item(),))
    return FiscalDocument.create(
        company_id=uuid4(),
        model=model,
        series=1,
        number=123,
        issuer=party(),
        recipient=party("52998224725"),
        items=lines,
        totals=totals,
    )


def authorized() -> FiscalDocument:
    return draft().start_issuing().authorize(
        access_key=access_key(), protocol=" 135260000000001 ", authorized_at=datetime.now(UTC)
    )


def test_draft_calculates_item_and_header_totals_with_decimal_precision() -> None:
    line = item(total="19.01")
    document = draft(items=(line,))

    assert line.products_amount == Decimal("20.00")
    assert line.total_amount == Decimal("19.01")
    assert line.unit_of_measure == "UN"
    assert line.code == "SKU-1"
    assert document.totals == FiscalDocumentTotals(
        products_amount=Decimal("20.00"),
        freight_amount=Decimal("1.00"),
        discount_amount=Decimal("2.00"),
        tax_amount=Decimal("1.60"),
        total_amount=Decimal("19.01"),
    )
    assert document.status is FiscalDocumentStatus.DRAFT


def test_complete_authorization_and_cancellation_lifecycle() -> None:
    issuing = draft().start_issuing()
    now = datetime.now(UTC)
    authorized_document = issuing.authorize(
        access_key=access_key(), protocol=" 135260000000001 ", authorized_at=now
    )
    cancelled = authorized_document.cancel(protocol=" 135260000000002 ", cancelled_at=now)

    assert issuing.status is FiscalDocumentStatus.ISSUING
    assert authorized_document.status is FiscalDocumentStatus.AUTHORIZED
    assert authorized_document.authorization_protocol == "135260000000001"
    assert cancelled.status is FiscalDocumentStatus.CANCELLED
    assert cancelled.cancellation_protocol == "135260000000002"
    assert [issuing.version, authorized_document.version, cancelled.version] == [2, 3, 4]
    assert cancelled.items == authorized_document.items
    with pytest.raises(FrozenInstanceError):
        cancelled.number = 999  # type: ignore[misc]


@pytest.mark.parametrize(
    ("method", "expected"),
    [("reject", FiscalDocumentStatus.REJECTED), ("deny", FiscalDocumentStatus.DENIED)],
)
def test_unsuccessful_sefaz_outcomes_are_definitive(method: str, expected: FiscalDocumentStatus) -> None:
    issuing = draft().start_issuing()
    changed = getattr(issuing, method)(code=" 539 ", reason=" Duplicidade ")

    assert changed.status is expected
    assert changed.rejection_code == "539"
    assert changed.rejection_reason == "Duplicidade"
    assert changed.access_key is None


def test_draft_can_be_revised_and_recalculates_totals() -> None:
    document = draft()
    replacement = item(total="19.00")

    revised = document.revise(items=(replacement,))

    assert revised.items == (replacement,)
    assert revised.totals.total_amount == Decimal("19.00")
    assert revised.version == 2


@pytest.mark.parametrize(
    "operation",
    [
        lambda value: value.start_issuing(),
        lambda value: value.reject(code="1", reason="x"),
        lambda value: value.deny(code="1", reason="x"),
    ],
)
def test_invalid_state_transitions_are_rejected(
    operation: Callable[[FiscalDocument], object],
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        operation(authorized())

    with pytest.raises(InvalidStateTransitionError):
        draft().cancel(protocol="1", cancelled_at=datetime.now(UTC))


@pytest.mark.parametrize("value", [authorized(), authorized().cancel(protocol="2", cancelled_at=datetime.now(UTC))])
def test_authorized_and_cancelled_documents_cannot_be_revised(value: FiscalDocument) -> None:
    with pytest.raises(ImmutableDocumentError):
        value.revise(items=(item(),))


def test_header_accepts_one_cent_legal_tolerance_and_rejects_more() -> None:
    line = item()
    calculated = FiscalDocumentTotals.from_items((line,))
    tolerated = replace(calculated, total_amount=calculated.total_amount + Decimal("0.01"))
    assert draft(items=(line,), totals=tolerated).totals == tolerated

    invalid = replace(calculated, tax_amount=calculated.tax_amount + Decimal("0.02"))
    with pytest.raises(TaxMismatchError):
        draft(items=(line,), totals=invalid)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": "0"},
        {"unit_price": "-1"},
        {"discount_amount": "30"},
        {"total_amount": "20"},
        {"quantity": "invalid"},
        {"quantity": "NaN"},
        {"code": " "},
    ],
)
def test_invalid_item_values_are_rejected(kwargs: dict[str, str]) -> None:
    values = {
        "product_id": uuid4(),
        "code": "SKU",
        "description": "Produto",
        "ncm": "95030099",
        "cfop": "5102",
        "unit_of_measure": "UN",
        "quantity": "1",
        "unit_price": "10",
        "tax_snapshot": taxes(),
    }
    values.update(kwargs)
    with pytest.raises((FiscalDomainError, TaxMismatchError)):
        FiscalDocumentItem.create(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [
        {"series": 0},
        {"number": 0},
        {"version": 0},
        {"items": ()},
    ],
)
def test_invalid_aggregate_identity_or_content_is_rejected(change: dict[str, object]) -> None:
    with pytest.raises(FiscalDomainError):
        replace(draft(), **change)  # type: ignore[arg-type]


def test_duplicate_item_ids_are_rejected() -> None:
    repeated = uuid4()
    with pytest.raises(FiscalDomainError):
        draft(items=(item(item_id=repeated), item(item_id=repeated)))


@pytest.mark.parametrize(
    "change",
    [
        {"status": FiscalDocumentStatus.AUTHORIZED},
        {"access_key": access_key()},
        {"status": FiscalDocumentStatus.REJECTED},
        {"rejection_code": "1"},
        {"status": FiscalDocumentStatus.CANCELLED},
        {"cancellation_protocol": "1", "cancelled_at": datetime.now(UTC)},
    ],
)
def test_state_metadata_must_be_complete_and_consistent(change: dict[str, object]) -> None:
    with pytest.raises(FiscalDomainError):
        replace(draft(), **change)  # type: ignore[arg-type]


def test_access_key_model_must_match_document_model() -> None:
    issuing = draft(model=FiscalDocumentModel.NFCE).start_issuing()
    with pytest.raises(FiscalDomainError):
        issuing.authorize(
            access_key=access_key("55"), protocol="1", authorized_at=datetime.now(UTC)
        )


@pytest.mark.parametrize(
    "action",
    [
        lambda value: value.authorize(
            access_key=access_key(), protocol=" ", authorized_at=datetime.now(UTC)
        ),
        lambda value: value.reject(code=" ", reason="x"),
        lambda value: value.deny(code="1", reason=" "),
    ],
)
def test_final_transition_requires_provider_metadata(
    action: Callable[[FiscalDocument], object],
) -> None:
    with pytest.raises(FiscalDomainError):
        action(draft().start_issuing())


def test_cancellation_requires_protocol() -> None:
    with pytest.raises(FiscalDomainError):
        authorized().cancel(protocol=" ", cancelled_at=datetime.now(UTC))


@pytest.mark.parametrize(
    "change",
    [
        {"tax_id": "1"},
        {"legal_name": " "},
        {"state_code": "S"},
        {"country_code": "BRA"},
        {"postal_code": "1"},
    ],
)
def test_fiscal_party_requires_valid_identity_and_address(change: dict[str, str]) -> None:
    with pytest.raises(FiscalDomainError):
        replace(party(), **change)


def test_totals_reject_negative_and_invalid_values() -> None:
    assert FiscalDocumentTotals.create(
        products_amount="10",
        freight_amount="1",
        discount_amount="1",
        tax_amount="2",
        total_amount="10",
    ).total_amount == Decimal("10.00")
    with pytest.raises(FiscalDomainError):
        FiscalDocumentTotals.create(
            products_amount="-1",
            freight_amount="0",
            discount_amount="0",
            tax_amount="0",
            total_amount="0",
        )
    with pytest.raises(FiscalDomainError):
        FiscalDocumentTotals.create(
            products_amount="invalid",
            freight_amount="0",
            discount_amount="0",
            tax_amount="0",
            total_amount="0",
        )


def test_sefaz_response_snapshot_is_normalized_and_validated() -> None:
    occurred_at = datetime.now(UTC)
    response = SefazResponseSnapshot(
        attempt_id=uuid4(),
        status_code=" 103 ",
        message=" Lote recebido ",
        occurred_at=occurred_at,
        protocol=" ",
    )

    assert response.status_code == "103"
    assert response.message == "Lote recebido"
    assert response.protocol is None
    assert SefazResponseSnapshot(
        attempt_id=uuid4(),
        status_code="100",
        message="Autorizado",
        occurred_at=occurred_at,
    ).protocol is None
    with pytest.raises(FiscalDomainError):
        SefazResponseSnapshot(
            attempt_id=uuid4(), status_code=" ", message="x", occurred_at=occurred_at
        )
    with pytest.raises(FiscalDomainError):
        SefazResponseSnapshot(
            attempt_id=uuid4(), status_code="100", message=" ", occurred_at=occurred_at
        )

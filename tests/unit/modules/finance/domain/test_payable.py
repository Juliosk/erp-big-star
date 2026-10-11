"""Pure Payable, installment and provisional-entry aggregate behavior."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    InstallmentMismatchError,
    InvalidPayableError,
    InvalidPayableStateError,
    InvalidProvisionalEntryError,
    Payable,
    PayableInstallment,
    PayableInstallmentStatus,
    PayableSegregationPolicy,
    PayableStatus,
    ProvisionalEntryOrigin,
    ProvisionalEntryStatus,
    ProvisionalFinancialEntry,
    SodViolationError,
)

FIRST_DUE_DATE = date(2026, 11, 10)
SECOND_DUE_DATE = date(2026, 12, 10)


def payable(
    *,
    nominal: str = "100.00",
    interest: str = "10.00",
    discount: str = "5.00",
    surcharge: str = "5.00",
    installments: tuple[tuple[date, Decimal], ...] | None = None,
    created_by: UUID | None = None,
) -> Payable:
    plan = installments or (
        (FIRST_DUE_DATE, Decimal("50.00")),
        (SECOND_DUE_DATE, Decimal("60.00")),
    )
    return Payable.create(
        company_id=uuid4(),
        number=" ap-157 ",
        supplier_id=uuid4(),
        supplier_tax_id="12.345.678/0001-95",
        created_by=created_by or uuid4(),
        provisional_entry_id=uuid4(),
        nominal_amount=Decimal(nominal),
        interest_amount=Decimal(interest),
        discount_amount=Decimal(discount),
        surcharge_amount=Decimal(surcharge),
        installment_plan=plan,
        currency="brl",
    )


def approved_payable(*, created_by: UUID | None = None) -> Payable:
    draft = payable(created_by=created_by)
    return draft.submit_for_approval().approve(
        approver_id=uuid4(),
        policy=PayableSegregationPolicy(Decimal("100.00")),
    )


def provisional() -> ProvisionalFinancialEntry:
    return ProvisionalFinancialEntry.create(
        company_id=uuid4(),
        origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
        source_id=uuid4(),
        source_version=2,
        supplier_id=uuid4(),
        supplier_tax_id="12.345.678/0001-95",
        amount=Decimal("110.00"),
        created_by=uuid4(),
        currency="brl",
    )


def perform_invalid_transition(method: str, title: Payable) -> None:
    if method == "approve":
        title.approve(
            approver_id=uuid4(),
            policy=PayableSegregationPolicy(Decimal("100.00")),
        )
    elif method == "reject":
        title.reject(rejected_by=uuid4(), reason="No")
    elif method == "schedule":
        title.schedule((uuid4(), uuid4()))
    elif method == "mark_installment_paid":
        title.mark_installment_paid(
            installment_number=1,
            paid_on=FIRST_DUE_DATE,
            payment_reference="REF",
        )
    else:
        title.submit_for_approval()


def test_payable_creation_normalizes_totals_and_installments() -> None:
    title = payable()

    assert title.number == "AP-157"
    assert title.supplier_tax_id == "12345678000195"
    assert title.currency == "BRL"
    assert title.status is PayableStatus.DRAFT
    assert title.total_amount == Decimal("110.00")
    assert title.paid_amount == Decimal("0.00")
    assert title.outstanding_amount == Decimal("110.00")
    assert tuple(item.number for item in title.installments) == (1, 2)
    assert all(item.company_id == title.company_id for item in title.installments)
    assert all(item.payable_id == title.id for item in title.installments)
    with pytest.raises(FrozenInstanceError):
        title.status = PayableStatus.APPROVED  # type: ignore[misc]


def test_payable_full_lifecycle_supports_partial_installment_payment() -> None:
    draft = payable()
    pending = draft.submit_for_approval()
    approved = pending.approve(
        approver_id=uuid4(),
        policy=PayableSegregationPolicy(Decimal("100.00")),
    )
    scheduled = approved.schedule((uuid4(), uuid4()))
    partially_paid = scheduled.mark_installment_paid(
        installment_number=1,
        paid_on=date(2026, 11, 5),
        payment_reference="BANK-SETTLEMENT-1",
    )
    paid = partially_paid.mark_installment_paid(
        installment_number=2,
        paid_on=date(2026, 12, 8),
        payment_reference="BANK-SETTLEMENT-2",
    )

    assert pending.status is PayableStatus.PENDING_APPROVAL
    assert approved.status is PayableStatus.APPROVED
    assert approved.decision_by is not None
    assert scheduled.status is PayableStatus.SCHEDULED
    assert partially_paid.status is PayableStatus.SCHEDULED
    assert partially_paid.paid_amount == Decimal("50.00")
    assert partially_paid.outstanding_amount == Decimal("60.00")
    assert paid.status is PayableStatus.PAID
    assert paid.paid_amount == paid.total_amount
    assert paid.outstanding_amount == Decimal("0.00")
    assert paid.version == 6


def test_high_value_self_approval_raises_the_public_sod_error() -> None:
    actor_id = uuid4()
    pending = payable(created_by=actor_id).submit_for_approval()

    with pytest.raises(SodViolationError) as captured:
        pending.approve(
            approver_id=actor_id,
            policy=PayableSegregationPolicy(Decimal("100.00")),
        )

    assert captured.value.code == "SOD_VIOLATION"
    assert pending.status is PayableStatus.PENDING_APPROVAL


def test_rejection_records_reason_and_is_terminal() -> None:
    rejected = (
        payable()
        .submit_for_approval()
        .reject(rejected_by=uuid4(), reason="  documento divergente  ")
    )

    assert rejected.status is PayableStatus.REJECTED
    assert rejected.decision_reason == "documento divergente"
    assert rejected.version == 3
    with pytest.raises(InvalidPayableStateError):
        rejected.schedule((uuid4(), uuid4()))


@pytest.mark.parametrize(
    ("method", "title"),
    [
        ("submit_for_approval", approved_payable()),
        ("approve", payable()),
        ("reject", payable()),
        ("schedule", payable()),
        (
            "mark_installment_paid",
            approved_payable(),
        ),
    ],
)
def test_payable_rejects_invalid_state_transitions(method: str, title: Payable) -> None:
    with pytest.raises(InvalidPayableStateError):
        perform_invalid_transition(method, title)


def test_schedule_and_payment_validate_installment_identity() -> None:
    approved = approved_payable()
    with pytest.raises(InstallmentMismatchError, match="one unique"):
        approved.schedule((uuid4(),))
    schedule_id = uuid4()
    with pytest.raises(InstallmentMismatchError, match="one unique"):
        approved.schedule((schedule_id, schedule_id))
    scheduled = approved.schedule((uuid4(), uuid4()))
    with pytest.raises(InstallmentMismatchError, match="does not belong"):
        scheduled.mark_installment_paid(
            installment_number=999,
            paid_on=FIRST_DUE_DATE,
            payment_reference="REF",
        )
    paid_first = scheduled.mark_installment_paid(
        installment_number=1,
        paid_on=FIRST_DUE_DATE,
        payment_reference="REF",
    )
    with pytest.raises(InvalidPayableStateError, match="scheduled installments"):
        paid_first.mark_installment_paid(
            installment_number=1,
            paid_on=FIRST_DUE_DATE,
            payment_reference="REF-REPLAY",
        )


def test_installment_requires_valid_data_and_lifecycle_metadata() -> None:
    valid = payable().installments[0]
    with pytest.raises(InvalidPayableError, match="positive integer"):
        replace(valid, number=0)
    with pytest.raises(InvalidPayableError, match="must be a date"):
        replace(valid, due_date=cast(date, datetime(2026, 11, 10, tzinfo=UTC)))
    with pytest.raises(InvalidPayableError, match="positive"):
        replace(valid, amount=Decimal("0"))
    with pytest.raises(InvalidPayableError, match="official status"):
        replace(valid, status=cast(PayableInstallmentStatus, "BAD"))
    with pytest.raises(InvalidPayableError, match="settlement metadata"):
        replace(valid, schedule_id=uuid4())
    with pytest.raises(InvalidPayableError, match="require schedule_id"):
        replace(valid, status=PayableInstallmentStatus.SCHEDULED)
    with pytest.raises(InvalidPayableError, match="payment metadata"):
        replace(
            valid,
            status=PayableInstallmentStatus.SCHEDULED,
            schedule_id=uuid4(),
            paid_on=FIRST_DUE_DATE,
        )
    with pytest.raises(InvalidPayableError, match="require schedule_id"):
        replace(valid, status=PayableInstallmentStatus.PAID, paid_on=FIRST_DUE_DATE)


def test_installment_schedule_and_payment_reject_replays_and_bad_payment_data() -> None:
    opened = payable().installments[0]
    scheduled = opened.schedule(uuid4())
    paid = scheduled.mark_paid(paid_on=FIRST_DUE_DATE, payment_reference=" REF-1 ")

    assert paid.status is PayableInstallmentStatus.PAID
    assert paid.payment_reference == "REF-1"
    with pytest.raises(InvalidPayableStateError):
        scheduled.schedule(uuid4())
    with pytest.raises(InvalidPayableStateError):
        opened.mark_paid(paid_on=FIRST_DUE_DATE, payment_reference="REF")
    with pytest.raises(InvalidPayableError, match="paid_on"):
        scheduled.mark_paid(
            paid_on=cast(date, datetime(2026, 11, 10, tzinfo=UTC)),
            payment_reference="REF",
        )
    with pytest.raises(InvalidPayableError, match="payment_reference"):
        scheduled.mark_paid(paid_on=FIRST_DUE_DATE, payment_reference=" ")


def test_payable_reconciles_installment_totals_and_ownership() -> None:
    title = payable()
    first, second = title.installments
    with pytest.raises(InstallmentMismatchError, match="at least one"):
        replace(title, installments=())
    with pytest.raises(InstallmentMismatchError, match="validated entities"):
        replace(title, installments=(cast(PayableInstallment, object()),))
    with pytest.raises(InstallmentMismatchError, match="same payable and company"):
        replace(title, installments=(replace(first, company_id=uuid4()), second))
    with pytest.raises(InstallmentMismatchError, match="sequential"):
        replace(title, installments=(replace(first, number=2), second))
    with pytest.raises(InstallmentMismatchError, match="must equal"):
        replace(title, installments=(replace(first, amount=Decimal("49.00")), second))
    with pytest.raises(InstallmentMismatchError, match="must equal"):
        payable(installments=((FIRST_DUE_DATE, Decimal("100.00")),))


def test_payable_header_and_decision_metadata_fail_closed() -> None:
    title = payable()
    assert replace(title, provisional_entry_id=None).provisional_entry_id is None
    with pytest.raises(InvalidPayableError, match="non-zero UUID"):
        replace(title, company_id=UUID(int=0))
    with pytest.raises(InvalidPayableError, match="number"):
        replace(title, number=" ")
    with pytest.raises(InvalidPayableError, match="supplier_tax_id"):
        replace(title, supplier_tax_id="123")
    with pytest.raises(InvalidPayableError, match="currency"):
        replace(title, currency="REAL")
    with pytest.raises(InvalidPayableError, match="finite Decimal"):
        replace(title, interest_amount=Decimal("NaN"))
    with pytest.raises(InvalidPayableError, match="unsupported monetary precision"):
        replace(title, interest_amount=Decimal("12345678901234567890123456789"))
    with pytest.raises(InvalidPayableError, match="positive after adjustments"):
        replace(title, discount_amount=Decimal("115.00"))
    with pytest.raises(InvalidPayableError, match="official payable status"):
        replace(title, status=cast(PayableStatus, "BAD"))
    with pytest.raises(InvalidPayableError, match="positive integer"):
        replace(title, version=0)
    with pytest.raises(InvalidPayableError, match="decision metadata"):
        replace(title, decision_by=uuid4())

    pending = title.submit_for_approval()
    with pytest.raises(InvalidPayableError, match="PayableSegregationPolicy"):
        pending.approve(approver_id=uuid4(), policy=cast(PayableSegregationPolicy, object()))
    with pytest.raises(InvalidPayableError, match="decision_by"):
        replace(approved_payable(), decision_by=None)
    with pytest.raises(InvalidPayableError, match="rejection reason"):
        replace(approved_payable(), decision_reason="not allowed")


def test_state_metadata_rejects_incoherent_installment_states() -> None:
    title = payable()
    scheduled_item = title.installments[0].schedule(uuid4())
    with pytest.raises(InvalidPayableError, match="undecided payables"):
        replace(title, installments=(scheduled_item, title.installments[1]))

    approved = approved_payable()
    approved_scheduled_item = approved.installments[0].schedule(uuid4())
    with pytest.raises(InvalidPayableError, match="approved payables"):
        replace(
            approved,
            installments=(approved_scheduled_item, approved.installments[1]),
        )

    rejected = title.submit_for_approval().reject(rejected_by=uuid4(), reason="No")
    rejected_scheduled = rejected.installments[0].schedule(uuid4())
    with pytest.raises(InvalidPayableError, match="rejected payables"):
        replace(rejected, installments=(rejected_scheduled, rejected.installments[1]))

    scheduled = approved.schedule((uuid4(), uuid4()))
    all_paid = tuple(
        item.mark_paid(paid_on=FIRST_DUE_DATE, payment_reference="REF")
        for item in scheduled.installments
    )
    with pytest.raises(InvalidPayableError, match="at least one scheduled"):
        replace(scheduled, installments=all_paid)
    with pytest.raises(InvalidPayableError, match="every installment"):
        replace(scheduled, status=PayableStatus.PAID)


def test_provisional_entry_lifecycle_preserves_source_fingerprint() -> None:
    entry = provisional()
    payable_id = uuid4()
    converted = entry.convert(payable_id)
    voided = provisional().void("  documento cancelado  ")

    assert entry.status is ProvisionalEntryStatus.OPEN
    assert entry.currency == "BRL"
    assert entry.supplier_tax_id == "12345678000195"
    assert entry.fingerprint.endswith(f"{entry.source_id}:v2")
    assert converted.status is ProvisionalEntryStatus.CONVERTED
    assert converted.payable_id == payable_id
    assert converted.version == 2
    assert voided.status is ProvisionalEntryStatus.VOIDED
    assert voided.void_reason == "documento cancelado"
    with pytest.raises(FrozenInstanceError):
        entry.status = ProvisionalEntryStatus.CONVERTED  # type: ignore[misc]


def test_provisional_entry_rejects_replayed_transitions_and_invalid_reason() -> None:
    converted = provisional().convert(uuid4())
    voided = provisional().void("cancelado")
    with pytest.raises(InvalidProvisionalEntryError, match="only open"):
        converted.convert(uuid4())
    with pytest.raises(InvalidProvisionalEntryError, match="only open"):
        voided.void("again")
    with pytest.raises(InvalidProvisionalEntryError, match="void_reason"):
        provisional().void(" ")


def test_provisional_entry_validates_identity_values_and_state_metadata() -> None:
    entry = provisional()
    with pytest.raises(InvalidProvisionalEntryError, match="non-zero UUID"):
        replace(entry, company_id=UUID(int=0))
    with pytest.raises(InvalidProvisionalEntryError, match="official source"):
        replace(entry, origin=cast(ProvisionalEntryOrigin, "BAD"))
    with pytest.raises(InvalidProvisionalEntryError, match="source_version"):
        replace(entry, source_version=0)
    with pytest.raises(InvalidProvisionalEntryError, match="supplier_tax_id"):
        replace(entry, supplier_tax_id="123")
    with pytest.raises(InvalidProvisionalEntryError, match="positive"):
        replace(entry, amount=Decimal("0"))
    with pytest.raises(InvalidProvisionalEntryError, match="finite Decimal"):
        replace(entry, amount=Decimal("NaN"))
    with pytest.raises(InvalidProvisionalEntryError, match="unsupported monetary precision"):
        replace(entry, amount=Decimal("12345678901234567890123456789"))
    with pytest.raises(InvalidProvisionalEntryError, match="currency"):
        replace(entry, currency="REAL")
    with pytest.raises(InvalidProvisionalEntryError, match="official provisional status"):
        replace(entry, status=cast(ProvisionalEntryStatus, "BAD"))
    with pytest.raises(InvalidProvisionalEntryError, match="version"):
        replace(entry, version=0)
    with pytest.raises(InvalidProvisionalEntryError, match="terminal metadata"):
        replace(entry, payable_id=uuid4())
    with pytest.raises(InvalidProvisionalEntryError, match="require payable_id"):
        replace(entry, status=ProvisionalEntryStatus.CONVERTED)
    with pytest.raises(InvalidProvisionalEntryError, match="cannot contain void_reason"):
        replace(entry.convert(uuid4()), void_reason="bad")
    with pytest.raises(InvalidProvisionalEntryError, match="cannot contain payable_id"):
        replace(entry.void("bad"), payable_id=uuid4())
    with pytest.raises(InvalidProvisionalEntryError, match="valid void_reason"):
        replace(entry, status=ProvisionalEntryStatus.VOIDED)

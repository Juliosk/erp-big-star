"""Pure tests for payment-batch eligibility, invariants and segregation."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    BankAccountType,
    BankPaymentConfirmation,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    InvalidTreasuryRuleError,
    MatchingGateStatus,
    PayableInstallmentPaymentSnapshot,
    PayableInstallmentStatus,
    PayableStatus,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchStatus,
    PaymentEligibilityPolicy,
    PaymentExecutionMode,
    PaymentInstallmentIneligibleError,
    TreasurySegregationPolicy,
    TreasurySodViolationError,
)

ZERO_UUID = UUID(int=0)


def bank_account(**changes: Any) -> BeneficiaryBankAccount:
    values: dict[str, Any] = {
        "bank_code": "001",
        "branch_number": "1234",
        "account_number": "123456",
        "account_digit": "X",
        "account_type": BankAccountType.CHECKING,
        "holder_name": "Forma Kids Ltda",
        "holder_tax_id": "12.345.678/0001-95",
    }
    values.update(changes)
    return BeneficiaryBankAccount(**values)


def snapshot(**changes: Any) -> PayableInstallmentPaymentSnapshot:
    values: dict[str, Any] = {
        "company_id": uuid4(),
        "payable_id": uuid4(),
        "installment_id": uuid4(),
        "supplier_id": uuid4(),
        "amount": Decimal("125.40"),
        "currency": "brl",
        "due_date": date(2026, 11, 10),
        "payable_status": PayableStatus.APPROVED,
        "installment_status": PayableInstallmentStatus.OPEN,
        "matching_status": MatchingGateStatus.MATCHED,
        "matching_session_id": uuid4(),
        "payable_created_by": uuid4(),
        "payable_approved_by": uuid4(),
        "beneficiary": bank_account(),
    }
    values.update(changes)
    return PayableInstallmentPaymentSnapshot(**values)


def batch_item(
    *,
    candidate: PayableInstallmentPaymentSnapshot | None = None,
    batch_id: UUID | None = None,
    item_id: UUID | None = None,
) -> PaymentBatchItem:
    return PaymentBatchItem.from_snapshot(
        item_id=item_id or uuid4(),
        batch_id=batch_id or uuid4(),
        snapshot=candidate or snapshot(),
        policy=PaymentEligibilityPolicy(),
    )


def payment_batch(
    *,
    items: tuple[PaymentBatchItem, ...] | None = None,
    batch_id: UUID | None = None,
    company_id: UUID | None = None,
    created_by: UUID | None = None,
    **changes: Any,
) -> PaymentBatch:
    resolved_batch_id = batch_id or uuid4()
    resolved_company_id = company_id or uuid4()
    if items is None:
        candidate = snapshot(company_id=resolved_company_id)
        items = (batch_item(candidate=candidate, batch_id=resolved_batch_id),)
    values: dict[str, Any] = {
        "id": resolved_batch_id,
        "company_id": resolved_company_id,
        "code": " pay-2026-001 ",
        "treasury_account_id": uuid4(),
        "scheduled_date": date(2026, 11, 11),
        "created_by": created_by or uuid4(),
        "remittance_format": BankRemittanceFormat.CNAB_240,
        "execution_mode": PaymentExecutionMode.DRY_RUN,
        "items": items,
    }
    values.update(changes)
    return PaymentBatch(**values)


def bank_confirmation(**changes: Any) -> BankPaymentConfirmation:
    values: dict[str, Any] = {
        "protocol": "BANK-2026-0001",
        "status_code": " paid ",
        "confirmed_at": datetime(2026, 11, 11, 15, 30, tzinfo=UTC),
        "confirmed_amount": Decimal("125.40"),
    }
    values.update(changes)
    return BankPaymentConfirmation(**values)


def submitted_batch() -> PaymentBatch:
    policy = TreasurySegregationPolicy()
    return (
        payment_batch()
        .submit_for_approval()
        .approve(actor_id=uuid4(), policy=policy)
        .release(actor_id=uuid4(), policy=policy)
        .mark_submitted(
            protocol="REM-2026-001",
            occurred_at=datetime(2026, 11, 11, 15, 0, tzinfo=UTC),
        )
    )


def test_bank_account_is_normalized_and_immutable() -> None:
    account = bank_account(branch_number=" 12-34 ", account_number="12.345-6")

    assert account.branch_number == "1234"
    assert account.account_number == "123456"
    assert account.holder_name == "Forma Kids Ltda"
    assert account.holder_tax_id == "12345678000195"
    with pytest.raises(FrozenInstanceError):
        account.bank_code = "999"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bank_code", "12"),
        ("branch_number", "123456"),
        ("account_number", ""),
        ("account_digit", ""),
        ("account_digit", "123"),
        ("account_type", "CHECKING"),
        ("holder_name", ""),
        ("holder_name", "x" * 121),
        ("holder_tax_id", "123"),
    ],
)
def test_bank_account_rejects_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(InvalidTreasuryRuleError):
        bank_account(**{field: value})


def test_bank_account_rejects_non_text_digit_and_text_fields() -> None:
    with pytest.raises(InvalidTreasuryRuleError, match="bank_code"):
        bank_account(bank_code=cast(str, 1))
    with pytest.raises(InvalidTreasuryRuleError, match="account_digit"):
        bank_account(account_digit=cast(str, 1))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", ZERO_UUID),
        ("payable_id", ZERO_UUID),
        ("amount", "1.00"),
        ("amount", Decimal("NaN")),
        ("amount", Decimal("1.001")),
        ("amount", Decimal("0.00")),
        ("amount", Decimal("1E+999999999")),
        ("currency", "REAL"),
        ("currency", "R"),
        ("due_date", "2026-11-10"),
        ("payable_status", "APPROVED"),
        ("installment_status", "OPEN"),
        ("matching_status", "MATCHED"),
        ("matching_session_id", ZERO_UUID),
        ("active_batch_id", ZERO_UUID),
        ("beneficiary", object()),
    ],
)
def test_payment_snapshot_rejects_invalid_contract(field: str, value: object) -> None:
    with pytest.raises(InvalidTreasuryRuleError):
        snapshot(**{field: value})


def test_payment_snapshot_accepts_optional_gate_and_batch_references() -> None:
    candidate = snapshot(
        matching_session_id=None,
        active_batch_id=uuid4(),
        payable_status=PayableStatus.SCHEDULED,
        installment_status=PayableInstallmentStatus.SCHEDULED,
    )

    assert candidate.currency == "BRL"
    assert candidate.matching_session_id is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"payable_status": PayableStatus.DRAFT}, "approved"),
        ({"installment_status": PayableInstallmentStatus.PAID}, "not open"),
        ({"matching_status": MatchingGateStatus.PENDING}, "matching gate"),
        ({"matching_session_id": None}, "matching gate"),
        ({"has_unresolved_block": True}, "governance block"),
        ({"active_batch_id": uuid4()}, "active batch"),
    ],
)
def test_eligibility_policy_rejects_every_fail_closed_gate(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(PaymentInstallmentIneligibleError, match=message):
        PaymentEligibilityPolicy().require_eligible(snapshot(**changes))


@pytest.mark.parametrize("matching", [MatchingGateStatus.MATCHED, MatchingGateStatus.OVERRIDDEN])
def test_eligibility_policy_accepts_completed_match_or_approved_override(
    matching: MatchingGateStatus,
) -> None:
    PaymentEligibilityPolicy().require_eligible(
        snapshot(
            payable_status=PayableStatus.SCHEDULED,
            installment_status=PayableInstallmentStatus.SCHEDULED,
            matching_status=matching,
        )
    )


def test_batch_item_is_built_from_eligible_immutable_snapshot() -> None:
    batch_id = uuid4()
    candidate = snapshot()
    item = batch_item(candidate=candidate, batch_id=batch_id)

    assert item.batch_id == batch_id
    assert item.payable_id == candidate.payable_id
    assert item.matching_session_id == candidate.matching_session_id
    assert item.currency == "BRL"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ZERO_UUID),
        ("amount", Decimal("-1.00")),
        ("currency", "R"),
        ("due_date", "2026-01-01"),
        ("beneficiary", object()),
    ],
)
def test_batch_item_rejects_invalid_values(field: str, value: object) -> None:
    item = batch_item()
    with pytest.raises(InvalidTreasuryRuleError):
        replace(item, **{field: value})  # type: ignore[arg-type]


def test_payment_batch_normalizes_identity_and_calculates_totals() -> None:
    batch_id = uuid4()
    company_id = uuid4()
    first = batch_item(
        candidate=snapshot(company_id=company_id, amount=Decimal("10.15")),
        batch_id=batch_id,
    )
    second = batch_item(
        candidate=snapshot(company_id=company_id, amount=Decimal("20.25")),
        batch_id=batch_id,
    )
    aggregate = payment_batch(batch_id=batch_id, company_id=company_id, items=(first, second))

    assert aggregate.code == "PAY-2026-001"
    assert aggregate.currency == "BRL"
    assert aggregate.total_amount == Decimal("30.40")
    assert aggregate.status is PaymentBatchStatus.DRAFT


def test_bank_confirmation_is_normalized_and_required_for_confirmed_batch() -> None:
    aggregate = submitted_batch()
    confirmation = bank_confirmation(confirmed_amount=aggregate.total_amount)
    confirmed = aggregate.confirm(confirmation)

    assert confirmed.bank_confirmation is not None
    assert confirmed.bank_confirmation.status_code == "PAID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protocol", ""),
        ("status_code", ""),
        ("confirmed_at", datetime(2026, 11, 11, 15, 30, tzinfo=UTC).replace(tzinfo=None)),
        ("confirmed_at", "2026-11-11T15:30:00Z"),
        ("confirmed_amount", Decimal("0.00")),
    ],
)
def test_bank_confirmation_rejects_invalid_evidence(field: str, value: object) -> None:
    with pytest.raises(InvalidTreasuryRuleError):
        bank_confirmation(**{field: value})


def test_payment_batch_never_equates_transmission_with_bank_confirmation() -> None:
    aggregate = payment_batch()

    with pytest.raises(InvalidTreasuryRuleError, match="requires explicit"):
        replace(aggregate, status=PaymentBatchStatus.CONFIRMED)
    with pytest.raises(InvalidTreasuryRuleError, match="only be attached"):
        replace(
            aggregate,
            status=PaymentBatchStatus.SUBMITTED,
            bank_confirmation=bank_confirmation(confirmed_amount=aggregate.total_amount),
        )
    with pytest.raises(InvalidTreasuryRuleError, match="reconcile"):
        replace(
            aggregate,
            status=PaymentBatchStatus.CONFIRMED,
            bank_confirmation=bank_confirmation(confirmed_amount=Decimal("1.00")),
        )


def test_payment_batch_state_machine_preserves_evidence_and_versions() -> None:
    policy = TreasurySegregationPolicy()
    draft = payment_batch()
    pending = draft.submit_for_approval()
    approver = uuid4()
    approved = pending.approve(actor_id=approver, policy=policy)
    executor = uuid4()
    released = approved.release(actor_id=executor, policy=policy)
    occurred_at = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
    submitted = released.mark_submitted(protocol=" REM-173 ", occurred_at=occurred_at)
    confirmation = bank_confirmation(confirmed_amount=submitted.total_amount)
    confirmed = submitted.confirm(confirmation)

    assert [
        value.version for value in (draft, pending, approved, released, submitted, confirmed)
    ] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert approved.approved_by == approver
    assert released.released_by == executor
    assert submitted.submission_protocol == "REM-173"
    assert submitted.submitted_at == occurred_at
    assert confirmed.status is PaymentBatchStatus.CONFIRMED


def test_payment_batch_reject_and_cancel_are_terminal_explained_decisions() -> None:
    policy = TreasurySegregationPolicy()
    rejected = (
        payment_batch()
        .submit_for_approval()
        .reject(
            actor_id=uuid4(),
            reason=" Dados bancarios divergentes ",
            policy=policy,
        )
    )
    cancelled = payment_batch().cancel(reason="Solicitacao retirada")

    assert rejected.status is PaymentBatchStatus.REJECTED
    assert rejected.transition_reason == "Dados bancarios divergentes"
    assert rejected.approved_by is None
    assert cancelled.status is PaymentBatchStatus.CANCELLED
    assert cancelled.version == 2


def test_payment_batch_state_machine_rejects_invalid_transitions_and_arguments() -> None:
    policy = TreasurySegregationPolicy()
    draft = payment_batch()
    pending = draft.submit_for_approval()
    approved = pending.approve(actor_id=uuid4(), policy=policy)
    released = approved.release(actor_id=uuid4(), policy=policy)
    submitted = released.mark_submitted(
        protocol="REM-173",
        occurred_at=datetime(2026, 11, 11, 15, 0, tzinfo=UTC),
    )

    with pytest.raises(InvalidTreasuryRuleError, match="must be DRAFT"):
        pending.submit_for_approval()
    with pytest.raises(InvalidTreasuryRuleError, match="must be PENDING_APPROVAL"):
        draft.approve(actor_id=uuid4(), policy=policy)
    with pytest.raises(InvalidTreasuryRuleError, match="must be PENDING_APPROVAL"):
        draft.reject(actor_id=uuid4(), reason="no", policy=policy)
    with pytest.raises(InvalidTreasuryRuleError, match="must be APPROVED"):
        pending.release(actor_id=uuid4(), policy=policy)
    with pytest.raises(InvalidTreasuryRuleError, match="must be RELEASED"):
        approved.mark_submitted(
            protocol="REM",
            occurred_at=datetime(2026, 11, 11, 15, 0, tzinfo=UTC),
        )
    with pytest.raises(InvalidTreasuryRuleError, match="must be SUBMITTED"):
        released.confirm(bank_confirmation(confirmed_amount=released.total_amount))
    with pytest.raises(InvalidTreasuryRuleError, match="BankPaymentConfirmation"):
        submitted.confirm(cast(BankPaymentConfirmation, object()))
    with pytest.raises(InvalidTreasuryRuleError, match="cannot be cancelled"):
        submitted.cancel(reason="too late")
    with pytest.raises(InvalidTreasuryRuleError, match="reason"):
        draft.cancel(reason=" ")
    with pytest.raises(InvalidTreasuryRuleError, match="reason"):
        pending.reject(actor_id=uuid4(), reason=" ", policy=policy)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"approved_by": ZERO_UUID}, "approved_by"),
        ({"released_by": ZERO_UUID}, "released_by"),
        ({"submission_protocol": ""}, "submission_protocol"),
        (
            {"submitted_at": datetime(2026, 11, 11, 15, 0, tzinfo=UTC).replace(tzinfo=None)},
            "submitted_at",
        ),
        ({"transition_reason": ""}, "transition_reason"),
        ({"status": PaymentBatchStatus.APPROVED}, "approved_by"),
        (
            {"status": PaymentBatchStatus.RELEASED, "approved_by": uuid4()},
            "released_by",
        ),
        (
            {
                "status": PaymentBatchStatus.SUBMITTED,
                "approved_by": uuid4(),
                "released_by": uuid4(),
            },
            "protocol and timestamp",
        ),
        ({"status": PaymentBatchStatus.REJECTED}, "transition reason"),
        ({"status": PaymentBatchStatus.CANCELLED}, "transition reason"),
    ],
)
def test_payment_batch_rejects_incomplete_lifecycle_evidence(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidTreasuryRuleError, match=message):
        replace(payment_batch(), **changes)  # type: ignore[arg-type]


def test_payment_batch_rejects_confirmation_that_predates_submission() -> None:
    submitted = submitted_batch()
    confirmation = bank_confirmation(
        confirmed_at=datetime(2026, 11, 11, 14, 59, tzinfo=UTC),
        confirmed_amount=submitted.total_amount,
    )

    with pytest.raises(InvalidTreasuryRuleError, match="cannot predate"):
        submitted.confirm(confirmation)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ZERO_UUID),
        ("code", ""),
        ("scheduled_date", "2026-11-11"),
        ("remittance_format", "CNAB_240"),
        ("execution_mode", "DRY_RUN"),
        ("status", "DRAFT"),
        ("version", 0),
        ("version", True),
        ("version", "1"),
        ("items", ()),
        ("items", []),
        ("items", (object(),)),
    ],
)
def test_payment_batch_rejects_invalid_header_or_collection(field: str, value: object) -> None:
    aggregate = payment_batch()
    with pytest.raises(InvalidTreasuryRuleError):
        replace(aggregate, **{field: value})  # type: ignore[arg-type]


def test_payment_batch_rejects_cross_scope_duplicate_and_mixed_currency_items() -> None:
    aggregate = payment_batch()
    item = aggregate.items[0]

    with pytest.raises(InvalidTreasuryRuleError, match="batch and company"):
        replace(aggregate, items=(replace(item, company_id=uuid4()),))
    with pytest.raises(InvalidTreasuryRuleError, match="batch and company"):
        replace(aggregate, items=(replace(item, batch_id=uuid4()),))
    with pytest.raises(InvalidTreasuryRuleError, match="twice"):
        replace(aggregate, items=(item, replace(item, id=uuid4())))
    with pytest.raises(InvalidTreasuryRuleError, match="single currency"):
        replace(
            aggregate,
            items=(item, replace(item, id=uuid4(), installment_id=uuid4(), currency="USD")),
        )


def test_treasury_sod_allows_independent_approver_and_executor() -> None:
    aggregate = payment_batch()
    policy = TreasurySegregationPolicy()
    batch_approver = uuid4()
    executor = uuid4()

    policy.require_can_approve(batch=aggregate, actor_id=batch_approver)
    policy.require_can_execute(
        batch=aggregate,
        actor_id=executor,
        batch_approved_by=batch_approver,
    )


@pytest.mark.parametrize("role", ["batch_creator", "payable_creator", "payable_approver"])
def test_treasury_sod_blocks_source_actors_from_approval_and_execution(role: str) -> None:
    aggregate = payment_batch()
    item = aggregate.items[0]
    actors = {
        "batch_creator": aggregate.created_by,
        "payable_creator": item.payable_created_by,
        "payable_approver": item.payable_approved_by,
    }
    actor = actors[role]
    policy = TreasurySegregationPolicy()

    with pytest.raises(TreasurySodViolationError) as approval_error:
        policy.require_can_approve(batch=aggregate, actor_id=actor)
    with pytest.raises(TreasurySodViolationError):
        policy.require_can_execute(
            batch=aggregate,
            actor_id=actor,
            batch_approved_by=uuid4(),
        )
    assert approval_error.value.code == "SOD_VIOLATION"


def test_treasury_sod_blocks_same_batch_approver_from_execution_by_default() -> None:
    aggregate = payment_batch()
    actor = uuid4()

    with pytest.raises(TreasurySodViolationError, match="approver"):
        TreasurySegregationPolicy().require_can_execute(
            batch=aggregate,
            actor_id=actor,
            batch_approved_by=actor,
        )


def test_treasury_sod_can_disable_only_the_approver_executor_split() -> None:
    aggregate = payment_batch()
    actor = uuid4()

    TreasurySegregationPolicy(require_distinct_executor=False).require_can_execute(
        batch=aggregate,
        actor_id=actor,
        batch_approved_by=actor,
    )


def test_treasury_sod_rejects_invalid_actor_references() -> None:
    aggregate = payment_batch()
    policy = TreasurySegregationPolicy()

    with pytest.raises(InvalidTreasuryRuleError, match="actor_id"):
        policy.require_can_approve(batch=aggregate, actor_id=ZERO_UUID)
    with pytest.raises(InvalidTreasuryRuleError, match="batch_approved_by"):
        policy.require_can_execute(
            batch=aggregate,
            actor_id=uuid4(),
            batch_approved_by=ZERO_UUID,
        )

"""Branch-complete tests for the pure M12 payment-request aggregate."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    BankAccountType,
    BeneficiaryBankAccount,
    InvalidPaymentRequestError,
    InvalidPaymentRequestTransitionError,
    PaymentApprovalAuthority,
    PaymentRequest,
    PaymentRequestItem,
    PaymentRequestStatus,
    TreasurySodViolationError,
)

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
TODAY = date(2026, 11, 11)


def _beneficiary() -> BeneficiaryBankAccount:
    return BeneficiaryBankAccount(
        bank_code="001",
        branch_number="1234",
        account_number="123456",
        account_digit="9",
        account_type=BankAccountType.CHECKING,
        holder_name="Fornecedor Big Star",
        holder_tax_id="12345678000195",
    )


def _item(*, company_id: object | None = None, **changes: Any) -> PaymentRequestItem:
    values: dict[str, Any] = {
        "id": uuid4(),
        "company_id": company_id or uuid4(),
        "payable_id": uuid4(),
        "installment_id": uuid4(),
        "supplier_id": uuid4(),
        "matching_session_id": uuid4(),
        "amount": Decimal("1250.50"),
        "currency": "brl",
        "due_date": date(2026, 12, 10),
        "beneficiary": _beneficiary(),
    }
    values.update(changes)
    return PaymentRequestItem(**values)


def _request(**changes: Any) -> PaymentRequest:
    company_id = changes.pop("company_id", uuid4())
    items = changes.pop("items", (_item(company_id=company_id),))
    values: dict[str, Any] = {
        "id": uuid4(),
        "company_id": company_id,
        "code": " pag-2026-001 ",
        "treasury_account_id": uuid4(),
        "requested_by": uuid4(),
        "requested_at": NOW,
        "scheduled_on": date(2026, 12, 10),
        "purpose": " Pagamento do fornecedor ",
        "items": items,
    }
    values.update(changes)
    return PaymentRequest(**values)


def test_payment_request_happy_path_is_immutable_versioned_and_governed() -> None:
    draft = _request()

    assert draft.code == "PAG-2026-001"
    assert draft.purpose == "Pagamento do fornecedor"
    assert draft.currency == "BRL"
    assert draft.total_amount == Decimal("1250.50")
    with pytest.raises(FrozenInstanceError):
        draft.code = "CHANGED"  # type: ignore[misc]

    workflow_id = uuid4()
    approver = uuid4()
    pending = draft.submit(workflow_instance_id=workflow_id)
    approved = pending.approve(
        authority=PaymentApprovalAuthority(approver, "brl", Decimal("2000.00")),
        occurred_at=NOW + timedelta(hours=1),
    )
    batched = approved.mark_batched(batch_id=uuid4())

    assert pending.status is PaymentRequestStatus.PENDING_APPROVAL
    assert approved.status is PaymentRequestStatus.APPROVED
    assert approved.approved_by == approver
    assert batched.status is PaymentRequestStatus.BATCHED
    assert batched.version == 4
    assert draft.status is PaymentRequestStatus.DRAFT


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": UUID(int=0)}, "non-zero UUID"),
        ({"amount": "1250.50"}, "finite Decimal"),
        ({"amount": Decimal("NaN")}, "finite Decimal"),
        ({"amount": Decimal("1.001")}, "two-decimal"),
        ({"amount": Decimal("0")}, "positive"),
        ({"currency": "REAL"}, "ISO 4217"),
        ({"due_date": "2026-12-10"}, "must be a date"),
        ({"beneficiary": object()}, "BeneficiaryBankAccount"),
    ],
)
def test_payment_request_item_rejects_invalid_values(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidPaymentRequestError, match=message):
        _item(**changes)


def test_payment_money_reports_unsupported_precision() -> None:
    with pytest.raises(InvalidPaymentRequestError, match="unsupported precision"):
        _item(amount=Decimal("1E+999999999"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"actor_id": UUID(int=0)}, "non-zero UUID"),
        ({"currency": 1}, "ISO 4217"),
        ({"maximum_amount": Decimal("0")}, "positive"),
    ],
)
def test_payment_authority_rejects_invalid_values(
    changes: dict[str, Any], message: str
) -> None:
    values: dict[str, Any] = {
        "actor_id": uuid4(),
        "currency": "BRL",
        "maximum_amount": Decimal("2000.00"),
    }
    values.update(changes)
    with pytest.raises(InvalidPaymentRequestError, match=message):
        PaymentApprovalAuthority(**values)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": UUID(int=0)}, "non-zero UUID"),
        ({"code": 1}, "must be text"),
        ({"code": ""}, "1 to 40"),
        ({"requested_at": NOW.replace(tzinfo=None)}, "timezone-aware"),
        ({"scheduled_on": "2026-12-10"}, "must be a date"),
        ({"purpose": ""}, "1 to 500"),
        ({"items": ()}, "must contain items"),
        ({"items": (object(),)}, "PaymentRequestItem"),
        ({"status": "DRAFT"}, "PaymentRequestStatus"),
        ({"version": True}, "positive integer"),
    ],
)
def test_payment_request_rejects_invalid_root_values(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidPaymentRequestError, match=message):
        _request(**changes)


def test_payment_request_rejects_cross_tenant_duplicate_and_mixed_currency_items() -> None:
    company_id = uuid4()
    item = _item(company_id=company_id)

    with pytest.raises(InvalidPaymentRequestError, match="company scope"):
        _request(company_id=uuid4(), items=(item,))
    with pytest.raises(InvalidPaymentRequestError, match="requested twice"):
        _request(company_id=company_id, items=(item, item))
    with pytest.raises(InvalidPaymentRequestError, match="one currency"):
        _request(
            company_id=company_id,
            items=(item, _item(company_id=company_id, currency="USD")),
        )


def test_submit_and_approval_fail_closed_for_state_sod_currency_limit_and_time() -> None:
    draft = _request()

    with pytest.raises(InvalidPaymentRequestTransitionError):
        draft.approve(
            authority=PaymentApprovalAuthority(uuid4(), "BRL", Decimal("2000.00")),
            occurred_at=NOW,
        )
    with pytest.raises(InvalidPaymentRequestError, match="workflow_instance_id"):
        draft.submit(workflow_instance_id=UUID(int=0))
    pending = draft.submit(workflow_instance_id=uuid4())

    with pytest.raises(InvalidPaymentRequestError, match="PaymentApprovalAuthority"):
        pending.approve(authority=object(), occurred_at=NOW)  # type: ignore[arg-type]
    with pytest.raises(TreasurySodViolationError):
        pending.approve(
            authority=PaymentApprovalAuthority(
                draft.requested_by, "BRL", Decimal("2000.00")
            ),
            occurred_at=NOW,
        )
    with pytest.raises(InvalidPaymentRequestError, match="does not cover"):
        pending.approve(
            authority=PaymentApprovalAuthority(uuid4(), "USD", Decimal("2000.00")),
            occurred_at=NOW,
        )
    with pytest.raises(InvalidPaymentRequestError, match="does not cover"):
        pending.approve(
            authority=PaymentApprovalAuthority(uuid4(), "BRL", Decimal("100.00")),
            occurred_at=NOW,
        )
    with pytest.raises(InvalidPaymentRequestError, match="timezone-aware"):
        pending.approve(
            authority=PaymentApprovalAuthority(uuid4(), "BRL", Decimal("2000.00")),
            occurred_at=NOW.replace(tzinfo=None),
        )
    with pytest.raises(InvalidPaymentRequestError, match="predate"):
        pending.approve(
            authority=PaymentApprovalAuthority(uuid4(), "BRL", Decimal("2000.00")),
            occurred_at=NOW - timedelta(seconds=1),
        )


def test_rejection_cancellation_and_batching_enforce_terminal_rules() -> None:
    draft = _request()
    pending = draft.submit(workflow_instance_id=uuid4())

    with pytest.raises(TreasurySodViolationError):
        pending.reject(actor_id=draft.requested_by, occurred_at=NOW, reason="blocked")
    with pytest.raises(InvalidPaymentRequestError, match="actor_id"):
        pending.reject(actor_id=UUID(int=0), occurred_at=NOW, reason="blocked")
    with pytest.raises(InvalidPaymentRequestError, match="timezone-aware"):
        pending.reject(actor_id=uuid4(), occurred_at=NOW.replace(tzinfo=None), reason="blocked")
    with pytest.raises(InvalidPaymentRequestError, match="predate"):
        pending.reject(
            actor_id=uuid4(),
            occurred_at=NOW - timedelta(seconds=1),
            reason="blocked",
        )
    rejected = pending.reject(
        actor_id=uuid4(), occurred_at=NOW + timedelta(minutes=1), reason="  divergência  "
    )
    assert rejected.status is PaymentRequestStatus.REJECTED
    assert rejected.transition_reason == "divergência"
    with pytest.raises(InvalidPaymentRequestTransitionError):
        rejected.cancel(reason="again")

    cancelled = pending.cancel(reason="  fornecedor solicitou  ")
    assert cancelled.status is PaymentRequestStatus.CANCELLED
    assert cancelled.transition_reason == "fornecedor solicitou"

    with pytest.raises(InvalidPaymentRequestTransitionError):
        pending.mark_batched(batch_id=uuid4())
    approved = pending.approve(
        authority=PaymentApprovalAuthority(uuid4(), "BRL", Decimal("2000.00")),
        occurred_at=NOW,
    )
    with pytest.raises(InvalidPaymentRequestError, match="batch_id"):
        approved.mark_batched(batch_id=UUID(int=0))


def test_payment_request_rehydration_rejects_incoherent_evidence() -> None:
    draft = _request()
    workflow_id = uuid4()
    actor = uuid4()
    pending = draft.submit(workflow_instance_id=workflow_id)
    approved = pending.approve(
        authority=PaymentApprovalAuthority(actor, "BRL", Decimal("2000.00")),
        occurred_at=NOW + timedelta(minutes=1),
    )

    invalid: list[tuple[PaymentRequest, dict[str, Any]]] = [
        (draft, {"workflow_instance_id": workflow_id}),
        (draft, {"status": PaymentRequestStatus.PENDING_APPROVAL}),
        (pending, {"workflow_instance_id": UUID(int=0)}),
        (pending, {"approved_by": actor}),
        (pending, {"approved_at": NOW.replace(tzinfo=None)}),
        (pending, {"transition_reason": "not terminal"}),
        (pending, {"status": PaymentRequestStatus.APPROVED}),
        (
            pending,
            {
                "status": PaymentRequestStatus.REJECTED,
                "approved_by": actor,
                "approved_at": NOW,
            },
        ),
        (
            pending,
            {
                "status": PaymentRequestStatus.APPROVED,
                "approved_by": actor,
                "approved_at": NOW - timedelta(seconds=1),
            },
        ),
        (
            pending,
            {
                "status": PaymentRequestStatus.APPROVED,
                "approved_by": draft.requested_by,
                "approved_at": NOW,
            },
        ),
        (approved, {"batch_id": uuid4()}),
        (approved, {"transition_reason": "not terminal"}),
        (
            approved,
            {"status": PaymentRequestStatus.BATCHED, "batch_id": UUID(int=0)},
        ),
        (draft, {"status": PaymentRequestStatus.CANCELLED}),
    ]

    for source, changes in invalid:
        with pytest.raises((InvalidPaymentRequestError, TreasurySodViolationError)):
            replace(source, **changes)

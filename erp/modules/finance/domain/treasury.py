"""Pure M12 treasury value objects and payment-execution policies."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from erp.modules.finance.domain.exceptions import (
    InvalidTreasuryRuleError,
    PaymentInstallmentIneligibleError,
    TreasurySodViolationError,
)
from erp.modules.finance.domain.payable import PayableInstallmentStatus, PayableStatus

_CENT = Decimal("0.01")


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidTreasuryRuleError(f"{field} must be a non-zero UUID.")
    return value


def _text(value: str, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidTreasuryRuleError(f"{field} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidTreasuryRuleError(f"{field} must contain between 1 and {maximum} characters.")
    return normalized


def _digits(value: str, field: str, *, lengths: tuple[int, ...]) -> str:
    if not isinstance(value, str):
        raise InvalidTreasuryRuleError(f"{field} must be text.")
    normalized = "".join(character for character in value if character.isdigit())
    if len(normalized) not in lengths:
        expected = ", ".join(str(length) for length in lengths)
        raise InvalidTreasuryRuleError(f"{field} must contain {expected} digits.")
    return normalized


def _money(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidTreasuryRuleError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidTreasuryRuleError(f"{field} must use supported monetary precision.") from error
    if normalized != value or normalized <= 0:
        raise InvalidTreasuryRuleError(f"{field} must be positive with at most two decimal places.")
    return normalized


def _aware_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidTreasuryRuleError(f"{field} must be a timezone-aware datetime.")
    return value


class BankAccountType(StrEnum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    PAYMENT = "PAYMENT"


class BankRemittanceFormat(StrEnum):
    CNAB_240 = "CNAB_240"
    CNAB_400 = "CNAB_400"
    PIX_API = "PIX_API"


class PaymentExecutionMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    HOMOLOGATION = "HOMOLOGATION"
    PRODUCTION = "PRODUCTION"


class MatchingGateStatus(StrEnum):
    MATCHED = "MATCHED"
    OVERRIDDEN = "OVERRIDDEN"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class PaymentBatchStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class BankPaymentConfirmation:
    """Immutable bank evidence required before a batch can be confirmed as paid."""

    protocol: str
    status_code: str
    confirmed_at: datetime
    confirmed_amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol", _text(self.protocol, "protocol", maximum=120))
        object.__setattr__(
            self,
            "status_code",
            _text(self.status_code, "status_code", maximum=40).upper(),
        )
        _aware_datetime(self.confirmed_at, "confirmed_at")
        object.__setattr__(
            self,
            "confirmed_amount",
            _money(self.confirmed_amount, "confirmed_amount"),
        )


@dataclass(frozen=True, slots=True)
class BeneficiaryBankAccount:
    """Restricted beneficiary bank data captured for an immutable batch item."""

    bank_code: str
    branch_number: str
    account_number: str
    account_digit: str
    account_type: BankAccountType
    holder_name: str
    holder_tax_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bank_code", _digits(self.bank_code, "bank_code", lengths=(3,)))
        object.__setattr__(
            self,
            "branch_number",
            _digits(self.branch_number, "branch_number", lengths=(1, 2, 3, 4, 5)),
        )
        object.__setattr__(
            self,
            "account_number",
            _digits(
                self.account_number,
                "account_number",
                lengths=tuple(range(1, 21)),
            ),
        )
        object.__setattr__(
            self, "account_digit", _text(self.account_digit, "account_digit", maximum=2)
        )
        if not isinstance(self.account_type, BankAccountType):
            raise InvalidTreasuryRuleError("account_type must be a BankAccountType.")
        object.__setattr__(self, "holder_name", _text(self.holder_name, "holder_name", maximum=120))
        object.__setattr__(
            self,
            "holder_tax_id",
            _digits(self.holder_tax_id, "holder_tax_id", lengths=(11, 14)),
        )


@dataclass(frozen=True, slots=True)
class PayableInstallmentPaymentSnapshot:
    """Immutable anti-corruption snapshot consumed by Treasury from Payables/Matching."""

    company_id: UUID
    payable_id: UUID
    installment_id: UUID
    supplier_id: UUID
    amount: Decimal
    currency: str
    due_date: date
    payable_status: PayableStatus
    installment_status: PayableInstallmentStatus
    matching_status: MatchingGateStatus
    matching_session_id: UUID | None
    payable_created_by: UUID
    payable_approved_by: UUID
    beneficiary: BeneficiaryBankAccount
    has_unresolved_block: bool = False
    active_batch_id: UUID | None = None

    def __post_init__(self) -> None:
        for field in (
            "company_id",
            "payable_id",
            "installment_id",
            "supplier_id",
            "payable_created_by",
            "payable_approved_by",
        ):
            object.__setattr__(self, field, _uuid(getattr(self, field), field))
        object.__setattr__(self, "amount", _money(self.amount, "amount"))
        object.__setattr__(self, "currency", _text(self.currency, "currency", maximum=3).upper())
        if len(self.currency) != 3:
            raise InvalidTreasuryRuleError("currency must use an ISO 4217 alpha-3 code.")
        if not isinstance(self.due_date, date):
            raise InvalidTreasuryRuleError("due_date must be a date.")
        if not isinstance(self.payable_status, PayableStatus):
            raise InvalidTreasuryRuleError("payable_status must be a PayableStatus.")
        if not isinstance(self.installment_status, PayableInstallmentStatus):
            raise InvalidTreasuryRuleError("installment_status must be a PayableInstallmentStatus.")
        if not isinstance(self.matching_status, MatchingGateStatus):
            raise InvalidTreasuryRuleError("matching_status must be a MatchingGateStatus.")
        if self.matching_session_id is not None:
            _uuid(self.matching_session_id, "matching_session_id")
        if self.active_batch_id is not None:
            _uuid(self.active_batch_id, "active_batch_id")
        if not isinstance(self.beneficiary, BeneficiaryBankAccount):
            raise InvalidTreasuryRuleError("beneficiary must be a BeneficiaryBankAccount.")


@dataclass(frozen=True, slots=True)
class PaymentEligibilityPolicy:
    """Fail-closed eligibility gate for payable installments entering Treasury."""

    def require_eligible(self, snapshot: PayableInstallmentPaymentSnapshot) -> None:
        if snapshot.payable_status not in {PayableStatus.APPROVED, PayableStatus.SCHEDULED}:
            raise PaymentInstallmentIneligibleError("Payable must be approved before batching.")
        if snapshot.installment_status not in {
            PayableInstallmentStatus.OPEN,
            PayableInstallmentStatus.SCHEDULED,
        }:
            raise PaymentInstallmentIneligibleError("Installment is not open for payment.")
        if (
            snapshot.matching_status
            not in {
                MatchingGateStatus.MATCHED,
                MatchingGateStatus.OVERRIDDEN,
            }
            or snapshot.matching_session_id is None
        ):
            raise PaymentInstallmentIneligibleError(
                "Installment requires a completed three-way matching gate."
            )
        if snapshot.has_unresolved_block:
            raise PaymentInstallmentIneligibleError(
                "Installment has an unresolved governance block."
            )
        if snapshot.active_batch_id is not None:
            raise PaymentInstallmentIneligibleError(
                "Installment already belongs to an active batch."
            )


@dataclass(frozen=True, slots=True)
class PaymentBatchItem:
    id: UUID
    company_id: UUID
    batch_id: UUID
    payable_id: UUID
    installment_id: UUID
    supplier_id: UUID
    amount: Decimal
    currency: str
    due_date: date
    matching_session_id: UUID
    payable_created_by: UUID
    payable_approved_by: UUID
    beneficiary: BeneficiaryBankAccount

    @classmethod
    def from_snapshot(
        cls,
        *,
        item_id: UUID,
        batch_id: UUID,
        snapshot: PayableInstallmentPaymentSnapshot,
        policy: PaymentEligibilityPolicy,
    ) -> PaymentBatchItem:
        policy.require_eligible(snapshot)
        assert snapshot.matching_session_id is not None
        return cls(
            id=item_id,
            company_id=snapshot.company_id,
            batch_id=batch_id,
            payable_id=snapshot.payable_id,
            installment_id=snapshot.installment_id,
            supplier_id=snapshot.supplier_id,
            amount=snapshot.amount,
            currency=snapshot.currency,
            due_date=snapshot.due_date,
            matching_session_id=snapshot.matching_session_id,
            payable_created_by=snapshot.payable_created_by,
            payable_approved_by=snapshot.payable_approved_by,
            beneficiary=snapshot.beneficiary,
        )

    def __post_init__(self) -> None:
        for field in (
            "id",
            "company_id",
            "batch_id",
            "payable_id",
            "installment_id",
            "supplier_id",
            "matching_session_id",
            "payable_created_by",
            "payable_approved_by",
        ):
            _uuid(getattr(self, field), field)
        _money(self.amount, "amount")
        currency = _text(self.currency, "currency", maximum=3).upper()
        if len(currency) != 3:
            raise InvalidTreasuryRuleError("currency must use an ISO 4217 alpha-3 code.")
        object.__setattr__(self, "currency", currency)
        if not isinstance(self.due_date, date):
            raise InvalidTreasuryRuleError("due_date must be a date.")
        if not isinstance(self.beneficiary, BeneficiaryBankAccount):
            raise InvalidTreasuryRuleError("beneficiary must be a BeneficiaryBankAccount.")


@dataclass(frozen=True, slots=True)
class PaymentBatch:
    id: UUID
    company_id: UUID
    code: str
    treasury_account_id: UUID
    scheduled_date: date
    created_by: UUID
    remittance_format: BankRemittanceFormat
    execution_mode: PaymentExecutionMode
    items: tuple[PaymentBatchItem, ...]
    status: PaymentBatchStatus = PaymentBatchStatus.DRAFT
    version: int = 1
    approved_by: UUID | None = None
    released_by: UUID | None = None
    submission_protocol: str | None = None
    submitted_at: datetime | None = None
    transition_reason: str | None = None
    bank_confirmation: BankPaymentConfirmation | None = None

    def __post_init__(self) -> None:
        for field in ("id", "company_id", "treasury_account_id", "created_by"):
            object.__setattr__(self, field, _uuid(getattr(self, field), field))
        object.__setattr__(self, "code", _text(self.code, "code", maximum=40).upper())
        if not isinstance(self.scheduled_date, date):
            raise InvalidTreasuryRuleError("scheduled_date must be a date.")
        if not isinstance(self.remittance_format, BankRemittanceFormat):
            raise InvalidTreasuryRuleError("remittance_format must be a BankRemittanceFormat.")
        if not isinstance(self.execution_mode, PaymentExecutionMode):
            raise InvalidTreasuryRuleError("execution_mode must be a PaymentExecutionMode.")
        if not isinstance(self.status, PaymentBatchStatus):
            raise InvalidTreasuryRuleError("status must be a PaymentBatchStatus.")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidTreasuryRuleError("version must be a positive integer.")
        if self.approved_by is not None:
            _uuid(self.approved_by, "approved_by")
        if self.released_by is not None:
            _uuid(self.released_by, "released_by")
        if self.submission_protocol is not None:
            object.__setattr__(
                self,
                "submission_protocol",
                _text(self.submission_protocol, "submission_protocol", maximum=120),
            )
        if self.submitted_at is not None:
            _aware_datetime(self.submitted_at, "submitted_at")
        if self.transition_reason is not None:
            object.__setattr__(
                self,
                "transition_reason",
                _text(self.transition_reason, "transition_reason", maximum=500),
            )
        if not isinstance(self.items, tuple) or not self.items:
            raise InvalidTreasuryRuleError("items must be a non-empty tuple.")
        installments: set[UUID] = set()
        currencies: set[str] = set()
        for item in self.items:
            if not isinstance(item, PaymentBatchItem):
                raise InvalidTreasuryRuleError("items must contain PaymentBatchItem values.")
            if item.company_id != self.company_id or item.batch_id != self.id:
                raise InvalidTreasuryRuleError("Batch items must share batch and company scope.")
            if item.installment_id in installments:
                raise InvalidTreasuryRuleError("An installment cannot appear twice in one batch.")
            installments.add(item.installment_id)
            currencies.add(item.currency)
        if len(currencies) != 1:
            raise InvalidTreasuryRuleError("A payment batch must use a single currency.")
        if self.status is PaymentBatchStatus.CONFIRMED:
            if self.bank_confirmation is None:
                raise InvalidTreasuryRuleError(
                    "A confirmed payment batch requires explicit bank confirmation."
                )
            if self.bank_confirmation.confirmed_amount != self.total_amount:
                raise InvalidTreasuryRuleError(
                    "Bank confirmation amount must reconcile with the complete batch."
                )
        elif self.bank_confirmation is not None:
            raise InvalidTreasuryRuleError(
                "Bank confirmation can only be attached to a confirmed payment batch."
            )
        self._validate_lifecycle_evidence()

    @property
    def currency(self) -> str:
        return self.items[0].currency

    @property
    def total_amount(self) -> Decimal:
        return sum((item.amount for item in self.items), start=Decimal("0.00"))

    def submit_for_approval(self) -> PaymentBatch:
        self._require_status(PaymentBatchStatus.DRAFT)
        return replace(
            self,
            status=PaymentBatchStatus.PENDING_APPROVAL,
            transition_reason=None,
            version=self.version + 1,
        )

    def approve(
        self,
        *,
        actor_id: UUID,
        policy: TreasurySegregationPolicy,
    ) -> PaymentBatch:
        self._require_status(PaymentBatchStatus.PENDING_APPROVAL)
        policy.require_can_approve(batch=self, actor_id=actor_id)
        return replace(
            self,
            status=PaymentBatchStatus.APPROVED,
            approved_by=actor_id,
            transition_reason=None,
            version=self.version + 1,
        )

    def reject(
        self,
        *,
        actor_id: UUID,
        reason: str,
        policy: TreasurySegregationPolicy,
    ) -> PaymentBatch:
        self._require_status(PaymentBatchStatus.PENDING_APPROVAL)
        policy.require_can_approve(batch=self, actor_id=actor_id)
        return replace(
            self,
            status=PaymentBatchStatus.REJECTED,
            transition_reason=_text(reason, "reason", maximum=500),
            version=self.version + 1,
        )

    def release(
        self,
        *,
        actor_id: UUID,
        policy: TreasurySegregationPolicy,
    ) -> PaymentBatch:
        self._require_status(PaymentBatchStatus.APPROVED)
        assert self.approved_by is not None
        policy.require_can_execute(
            batch=self,
            actor_id=actor_id,
            batch_approved_by=self.approved_by,
        )
        return replace(
            self,
            status=PaymentBatchStatus.RELEASED,
            released_by=actor_id,
            transition_reason=None,
            version=self.version + 1,
        )

    def mark_submitted(
        self,
        *,
        protocol: str,
        occurred_at: datetime,
    ) -> PaymentBatch:
        self._require_status(PaymentBatchStatus.RELEASED)
        return replace(
            self,
            status=PaymentBatchStatus.SUBMITTED,
            submission_protocol=_text(protocol, "protocol", maximum=120),
            submitted_at=_aware_datetime(occurred_at, "occurred_at"),
            transition_reason=None,
            version=self.version + 1,
        )

    def confirm(self, confirmation: BankPaymentConfirmation) -> PaymentBatch:
        self._require_status(PaymentBatchStatus.SUBMITTED)
        if not isinstance(confirmation, BankPaymentConfirmation):
            raise InvalidTreasuryRuleError("confirmation must be a BankPaymentConfirmation.")
        return replace(
            self,
            status=PaymentBatchStatus.CONFIRMED,
            bank_confirmation=confirmation,
            transition_reason=None,
            version=self.version + 1,
        )

    def cancel(self, *, reason: str) -> PaymentBatch:
        if self.status not in {
            PaymentBatchStatus.DRAFT,
            PaymentBatchStatus.PENDING_APPROVAL,
            PaymentBatchStatus.APPROVED,
            PaymentBatchStatus.RELEASED,
        }:
            raise InvalidTreasuryRuleError(
                f"Payment batch in {self.status.value} cannot be cancelled."
            )
        return replace(
            self,
            status=PaymentBatchStatus.CANCELLED,
            transition_reason=_text(reason, "reason", maximum=500),
            version=self.version + 1,
        )

    def _require_status(self, expected: PaymentBatchStatus) -> None:
        if self.status is not expected:
            raise InvalidTreasuryRuleError(
                f"Payment batch must be {expected.value}, not {self.status.value}."
            )

    def _validate_lifecycle_evidence(self) -> None:
        if (
            self.status
            in {
                PaymentBatchStatus.APPROVED,
                PaymentBatchStatus.RELEASED,
                PaymentBatchStatus.SUBMITTED,
                PaymentBatchStatus.CONFIRMED,
            }
            and self.approved_by is None
        ):
            raise InvalidTreasuryRuleError("Approved payment-batch states require approved_by.")
        if (
            self.status
            in {
                PaymentBatchStatus.RELEASED,
                PaymentBatchStatus.SUBMITTED,
                PaymentBatchStatus.CONFIRMED,
            }
            and self.released_by is None
        ):
            raise InvalidTreasuryRuleError("Released payment-batch states require released_by.")
        if self.status in {PaymentBatchStatus.SUBMITTED, PaymentBatchStatus.CONFIRMED} and (
            self.submission_protocol is None or self.submitted_at is None
        ):
            raise InvalidTreasuryRuleError(
                "Submitted payment-batch states require protocol and timestamp."
            )
        if self.status in {PaymentBatchStatus.REJECTED, PaymentBatchStatus.CANCELLED} and (
            self.transition_reason is None
        ):
            raise InvalidTreasuryRuleError("Terminal decisions require a transition reason.")
        if (
            self.status is PaymentBatchStatus.CONFIRMED
            and self.bank_confirmation is not None
            and self.submitted_at is not None
            and self.bank_confirmation.confirmed_at < self.submitted_at
        ):
            raise InvalidTreasuryRuleError(
                "Bank confirmation cannot predate payment-batch submission."
            )


@dataclass(frozen=True, slots=True)
class TreasurySegregationPolicy:
    """Enforce payable-origin and batch maker-checker separation."""

    require_distinct_executor: bool = True

    def require_can_approve(self, *, batch: PaymentBatch, actor_id: UUID) -> None:
        actor = _uuid(actor_id, "actor_id")
        self._require_not_source_actor(batch=batch, actor_id=actor)

    def require_can_execute(
        self,
        *,
        batch: PaymentBatch,
        actor_id: UUID,
        batch_approved_by: UUID,
    ) -> None:
        actor = _uuid(actor_id, "actor_id")
        approver = _uuid(batch_approved_by, "batch_approved_by")
        self._require_not_source_actor(batch=batch, actor_id=actor)
        if self.require_distinct_executor and actor == approver:
            raise TreasurySodViolationError(
                "The payment-batch approver cannot execute the same batch."
            )

    @staticmethod
    def _require_not_source_actor(*, batch: PaymentBatch, actor_id: UUID) -> None:
        if actor_id == batch.created_by:
            raise TreasurySodViolationError(
                "The payment-batch creator cannot approve or execute the same batch."
            )
        if any(
            actor_id in {item.payable_created_by, item.payable_approved_by} for item in batch.items
        ):
            raise TreasurySodViolationError(
                "A payable creator or approver cannot approve or execute its payment batch."
            )


__all__ = [
    "BankAccountType",
    "BankPaymentConfirmation",
    "BankRemittanceFormat",
    "BeneficiaryBankAccount",
    "MatchingGateStatus",
    "PayableInstallmentPaymentSnapshot",
    "PaymentBatch",
    "PaymentBatchItem",
    "PaymentBatchStatus",
    "PaymentEligibilityPolicy",
    "PaymentExecutionMode",
    "TreasurySegregationPolicy",
]

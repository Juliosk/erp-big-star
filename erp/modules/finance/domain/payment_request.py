"""Pure M12 Treasury payment-request aggregate."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from erp.modules.finance.domain.exceptions import (
    InvalidPaymentRequestError,
    InvalidPaymentRequestTransitionError,
    TreasurySodViolationError,
)
from erp.modules.finance.domain.treasury import BeneficiaryBankAccount

_CENT = Decimal("0.01")


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidPaymentRequestError(f"{field} must be a non-zero UUID.")
    return value


def _text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidPaymentRequestError(f"{field} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidPaymentRequestError(f"{field} must contain 1 to {maximum} characters.")
    return normalized


def _money(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidPaymentRequestError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidPaymentRequestError(f"{field} uses unsupported precision.") from error
    if normalized != value or normalized <= 0:
        raise InvalidPaymentRequestError(f"{field} must be positive with two-decimal precision.")
    return normalized


def _currency(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value.strip().upper()) is None:
        raise InvalidPaymentRequestError("currency must use ISO 4217 alpha-3 format.")
    return value.strip().upper()


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidPaymentRequestError(f"{field} must be timezone-aware.")
    return value


class PaymentRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    BATCHED = "BATCHED"


@dataclass(frozen=True, slots=True)
class PaymentRequestItem:
    id: UUID
    company_id: UUID
    payable_id: UUID
    installment_id: UUID
    supplier_id: UUID
    matching_session_id: UUID
    amount: Decimal
    currency: str
    due_date: date
    beneficiary: BeneficiaryBankAccount

    def __post_init__(self) -> None:
        for field in (
            "id",
            "company_id",
            "payable_id",
            "installment_id",
            "supplier_id",
            "matching_session_id",
        ):
            _uuid(getattr(self, field), field)
        object.__setattr__(self, "amount", _money(self.amount, "amount"))
        object.__setattr__(self, "currency", _currency(self.currency))
        if not isinstance(self.due_date, date):
            raise InvalidPaymentRequestError("due_date must be a date.")
        if not isinstance(self.beneficiary, BeneficiaryBankAccount):
            raise InvalidPaymentRequestError("beneficiary must be a BeneficiaryBankAccount.")


@dataclass(frozen=True, slots=True)
class PaymentApprovalAuthority:
    actor_id: UUID
    currency: str
    maximum_amount: Decimal

    def __post_init__(self) -> None:
        _uuid(self.actor_id, "actor_id")
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(
            self, "maximum_amount", _money(self.maximum_amount, "maximum_amount")
        )


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    id: UUID
    company_id: UUID
    code: str
    treasury_account_id: UUID
    requested_by: UUID
    requested_at: datetime
    scheduled_on: date
    purpose: str
    items: tuple[PaymentRequestItem, ...]
    status: PaymentRequestStatus = PaymentRequestStatus.DRAFT
    version: int = 1
    workflow_instance_id: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    batch_id: UUID | None = None
    transition_reason: str | None = None

    def __post_init__(self) -> None:
        for field in ("id", "company_id", "treasury_account_id", "requested_by"):
            _uuid(getattr(self, field), field)
        object.__setattr__(self, "code", _text(self.code, "code", 40).upper())
        _aware(self.requested_at, "requested_at")
        if not isinstance(self.scheduled_on, date):
            raise InvalidPaymentRequestError("scheduled_on must be a date.")
        object.__setattr__(self, "purpose", _text(self.purpose, "purpose", 500))
        if not isinstance(self.items, tuple) or not self.items:
            raise InvalidPaymentRequestError("Payment request must contain items.")
        if any(not isinstance(item, PaymentRequestItem) for item in self.items):
            raise InvalidPaymentRequestError("items must contain PaymentRequestItem values.")
        if any(item.company_id != self.company_id for item in self.items):
            raise InvalidPaymentRequestError("Payment-request items must share company scope.")
        installment_ids = [item.installment_id for item in self.items]
        if len(installment_ids) != len(set(installment_ids)):
            raise InvalidPaymentRequestError("An installment cannot be requested twice.")
        if len({item.currency for item in self.items}) != 1:
            raise InvalidPaymentRequestError("Payment request must use one currency.")
        if not isinstance(self.status, PaymentRequestStatus):
            raise InvalidPaymentRequestError("status must be a PaymentRequestStatus.")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidPaymentRequestError("version must be a positive integer.")
        self._validate_evidence()

    @property
    def currency(self) -> str:
        return self.items[0].currency

    @property
    def total_amount(self) -> Decimal:
        return sum((item.amount for item in self.items), start=Decimal("0.00"))

    def submit(self, *, workflow_instance_id: UUID) -> PaymentRequest:
        self._require(PaymentRequestStatus.DRAFT)
        return replace(
            self,
            status=PaymentRequestStatus.PENDING_APPROVAL,
            workflow_instance_id=_uuid(workflow_instance_id, "workflow_instance_id"),
            version=self.version + 1,
        )

    def approve(
        self,
        *,
        authority: PaymentApprovalAuthority,
        occurred_at: datetime,
    ) -> PaymentRequest:
        self._require(PaymentRequestStatus.PENDING_APPROVAL)
        if not isinstance(authority, PaymentApprovalAuthority):
            raise InvalidPaymentRequestError("authority must be a PaymentApprovalAuthority.")
        if authority.actor_id == self.requested_by:
            raise TreasurySodViolationError("Payment requester cannot approve the same request.")
        if authority.currency != self.currency or authority.maximum_amount < self.total_amount:
            raise InvalidPaymentRequestError("Approval authority does not cover this payment request.")
        instant = _aware(occurred_at, "occurred_at")
        if instant < self.requested_at:
            raise InvalidPaymentRequestError("approved_at cannot predate requested_at.")
        return replace(
            self,
            status=PaymentRequestStatus.APPROVED,
            approved_by=authority.actor_id,
            approved_at=instant,
            version=self.version + 1,
        )

    def reject(self, *, actor_id: UUID, occurred_at: datetime, reason: str) -> PaymentRequest:
        self._require(PaymentRequestStatus.PENDING_APPROVAL)
        actor = _uuid(actor_id, "actor_id")
        if actor == self.requested_by:
            raise TreasurySodViolationError("Payment requester cannot reject the same request.")
        instant = _aware(occurred_at, "occurred_at")
        if instant < self.requested_at:
            raise InvalidPaymentRequestError("decision cannot predate requested_at.")
        return replace(
            self,
            status=PaymentRequestStatus.REJECTED,
            approved_by=actor,
            approved_at=instant,
            transition_reason=_text(reason, "reason", 500),
            version=self.version + 1,
        )

    def cancel(self, *, reason: str) -> PaymentRequest:
        if self.status not in {
            PaymentRequestStatus.DRAFT,
            PaymentRequestStatus.PENDING_APPROVAL,
            PaymentRequestStatus.APPROVED,
        }:
            raise InvalidPaymentRequestTransitionError(
                "Payment request cannot be cancelled in this state."
            )
        return replace(
            self,
            status=PaymentRequestStatus.CANCELLED,
            transition_reason=_text(reason, "reason", 500),
            version=self.version + 1,
        )

    def mark_batched(self, *, batch_id: UUID) -> PaymentRequest:
        self._require(PaymentRequestStatus.APPROVED)
        return replace(
            self,
            status=PaymentRequestStatus.BATCHED,
            batch_id=_uuid(batch_id, "batch_id"),
            version=self.version + 1,
        )

    def _require(self, status: PaymentRequestStatus) -> None:
        if self.status is not status:
            raise InvalidPaymentRequestTransitionError(
                f"Payment request must be {status.value}, not {self.status.value}."
            )

    def _validate_evidence(self) -> None:
        if self.workflow_instance_id is not None:
            _uuid(self.workflow_instance_id, "workflow_instance_id")
        if self.approved_by is not None:
            _uuid(self.approved_by, "approved_by")
        if self.approved_at is not None:
            _aware(self.approved_at, "approved_at")
        if self.batch_id is not None:
            _uuid(self.batch_id, "batch_id")
        if self.transition_reason is not None:
            object.__setattr__(
                self, "transition_reason", _text(self.transition_reason, "transition_reason", 500)
            )
        if self.status is PaymentRequestStatus.DRAFT and any(
            value is not None
            for value in (
                self.workflow_instance_id,
                self.approved_by,
                self.approved_at,
                self.batch_id,
                self.transition_reason,
            )
        ):
            raise InvalidPaymentRequestError("Draft payment requests cannot carry decisions.")
        if self.status in {
            PaymentRequestStatus.PENDING_APPROVAL,
            PaymentRequestStatus.APPROVED,
            PaymentRequestStatus.REJECTED,
            PaymentRequestStatus.BATCHED,
        } and self.workflow_instance_id is None:
            raise InvalidPaymentRequestError("Governed payment-request states require workflow.")
        if self.status is PaymentRequestStatus.PENDING_APPROVAL and (
            self.approved_by is not None or self.approved_at is not None
        ):
            raise InvalidPaymentRequestError(
                "Pending payment requests cannot carry decision evidence."
            )
        if self.status in {
            PaymentRequestStatus.APPROVED,
            PaymentRequestStatus.REJECTED,
            PaymentRequestStatus.BATCHED,
        } and (self.approved_by is None or self.approved_at is None):
            raise InvalidPaymentRequestError("Decided payment-request states require decision evidence.")
        if (
            self.approved_at is not None
            and self.approved_at < self.requested_at
        ):
            raise InvalidPaymentRequestError("Decision cannot predate payment request.")
        if self.approved_by is not None and self.approved_by == self.requested_by:
            raise TreasurySodViolationError("Payment requester cannot decide the same request.")
        if (self.status is PaymentRequestStatus.BATCHED) != (self.batch_id is not None):
            raise InvalidPaymentRequestError("batch_id is exclusive to batched payment requests.")
        if self.status in {
            PaymentRequestStatus.PENDING_APPROVAL,
            PaymentRequestStatus.APPROVED,
            PaymentRequestStatus.BATCHED,
        } and self.transition_reason is not None:
            raise InvalidPaymentRequestError("Non-terminal states cannot carry a decision reason.")
        if self.status in {
            PaymentRequestStatus.REJECTED,
            PaymentRequestStatus.CANCELLED,
        } and self.transition_reason is None:
            raise InvalidPaymentRequestError("Terminal decisions require a reason.")


__all__ = [
    "PaymentApprovalAuthority",
    "PaymentRequest",
    "PaymentRequestItem",
    "PaymentRequestStatus",
]

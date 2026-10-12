"""Pure M12 payable aggregate and installment lifecycle."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.finance.domain.exceptions import (
    InstallmentMismatchError,
    InvalidPayableError,
    InvalidPayableStateError,
)
from erp.modules.finance.domain.segregation import PayableSegregationPolicy

_CENT = Decimal("0.01")


class PayableStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"


class PayableInstallmentStatus(StrEnum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidPayableError(f"{field} must be a non-zero UUID.")
    return value


def _money(
    value: Decimal,
    field: str,
    *,
    positive: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidPayableError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidPayableError(f"{field} uses unsupported monetary precision.") from error
    if normalized != value or normalized < 0 or (positive and normalized == 0):
        qualifier = "positive" if positive else "non-negative"
        raise InvalidPayableError(f"{field} must be {qualifier} with at most two decimal places.")
    return normalized


def _text(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > maximum:
        raise InvalidPayableError(f"{field} must contain between 1 and {maximum} characters.")
    return normalized


def _tax_id(value: str) -> str:
    source = value if isinstance(value, str) else ""
    normalized = "".join(character for character in source if character.isdigit())
    if len(normalized) not in {11, 14}:
        raise InvalidPayableError("supplier_tax_id must be a CPF or CNPJ.")
    return normalized


def _currency(value: str) -> str:
    normalized = value.strip().upper() if isinstance(value, str) else ""
    if len(normalized) != 3 or not normalized.isalpha() or not normalized.isascii():
        raise InvalidPayableError("currency must be a three-letter ASCII code.")
    return normalized


@dataclass(frozen=True, slots=True)
class PayableInstallment:
    id: UUID
    company_id: UUID
    payable_id: UUID
    number: int
    due_date: date
    amount: Decimal
    status: PayableInstallmentStatus
    schedule_id: UUID | None = None
    paid_on: date | None = None
    payment_reference: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.id, "installment.id")
        _uuid(self.company_id, "installment.company_id")
        _uuid(self.payable_id, "installment.payable_id")
        if type(self.number) is not int or self.number < 1:
            raise InvalidPayableError("installment.number must be a positive integer.")
        if type(self.due_date) is not date:
            raise InvalidPayableError("installment.due_date must be a date.")
        object.__setattr__(self, "amount", _money(self.amount, "installment.amount", positive=True))
        if not isinstance(self.status, PayableInstallmentStatus):
            raise InvalidPayableError("installment.status must be an official status.")
        if self.status is PayableInstallmentStatus.OPEN:
            if any(
                value is not None
                for value in (self.schedule_id, self.paid_on, self.payment_reference)
            ):
                raise InvalidPayableError("open installments cannot contain settlement metadata.")
        elif self.status is PayableInstallmentStatus.SCHEDULED:
            if self.schedule_id is None:
                raise InvalidPayableError("scheduled installments require schedule_id.")
            _uuid(self.schedule_id, "installment.schedule_id")
            if self.paid_on is not None or self.payment_reference is not None:
                raise InvalidPayableError("scheduled installments cannot contain payment metadata.")
        else:
            if self.schedule_id is None:
                raise InvalidPayableError("paid installments require schedule_id.")
            _uuid(self.schedule_id, "installment.schedule_id")
            if type(self.paid_on) is not date:
                raise InvalidPayableError("paid installments require paid_on as a date.")
            object.__setattr__(
                self,
                "payment_reference",
                _text(self.payment_reference or "", "payment_reference", maximum=128),
            )

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        payable_id: UUID,
        number: int,
        due_date: date,
        amount: Decimal,
    ) -> PayableInstallment:
        return cls(
            id=uuid4(),
            company_id=company_id,
            payable_id=payable_id,
            number=number,
            due_date=due_date,
            amount=amount,
            status=PayableInstallmentStatus.OPEN,
        )

    def schedule(self, schedule_id: UUID) -> PayableInstallment:
        if self.status is not PayableInstallmentStatus.OPEN:
            raise InvalidPayableStateError("only open installments can be scheduled.")
        return replace(
            self,
            status=PayableInstallmentStatus.SCHEDULED,
            schedule_id=_uuid(schedule_id, "installment.schedule_id"),
        )

    def mark_paid(self, *, paid_on: date, payment_reference: str) -> PayableInstallment:
        if self.status is not PayableInstallmentStatus.SCHEDULED:
            raise InvalidPayableStateError("only scheduled installments can be paid.")
        return replace(
            self,
            status=PayableInstallmentStatus.PAID,
            paid_on=paid_on,
            payment_reference=payment_reference,
        )

    def release_schedule(self) -> PayableInstallment:
        """Return an unpaid installment to OPEN after its source is cancelled."""
        if self.status is PayableInstallmentStatus.PAID:
            raise InvalidPayableStateError("paid installments cannot release their schedule.")
        if self.status is PayableInstallmentStatus.OPEN:
            return self
        return replace(
            self,
            status=PayableInstallmentStatus.OPEN,
            schedule_id=None,
        )


@dataclass(frozen=True, slots=True)
class Payable:
    id: UUID
    company_id: UUID
    number: str
    supplier_id: UUID
    supplier_tax_id: str
    provisional_entry_id: UUID | None
    currency: str
    nominal_amount: Decimal
    interest_amount: Decimal
    discount_amount: Decimal
    surcharge_amount: Decimal
    status: PayableStatus
    installments: tuple[PayableInstallment, ...]
    created_by: UUID
    decision_by: UUID | None
    decision_reason: str | None
    version: int

    def __post_init__(self) -> None:
        _uuid(self.id, "id")
        _uuid(self.company_id, "company_id")
        _uuid(self.supplier_id, "supplier_id")
        _uuid(self.created_by, "created_by")
        if self.provisional_entry_id is not None:
            _uuid(self.provisional_entry_id, "provisional_entry_id")
        object.__setattr__(self, "number", _text(self.number, "number", maximum=64).upper())
        object.__setattr__(self, "supplier_tax_id", _tax_id(self.supplier_tax_id))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(
            self, "nominal_amount", _money(self.nominal_amount, "nominal_amount", positive=True)
        )
        object.__setattr__(self, "interest_amount", _money(self.interest_amount, "interest_amount"))
        object.__setattr__(self, "discount_amount", _money(self.discount_amount, "discount_amount"))
        object.__setattr__(
            self, "surcharge_amount", _money(self.surcharge_amount, "surcharge_amount")
        )
        if self.total_amount <= 0:
            raise InvalidPayableError("payable total_amount must be positive after adjustments.")
        if not isinstance(self.status, PayableStatus):
            raise InvalidPayableError("status must be an official payable status.")
        if type(self.version) is not int or self.version < 1:
            raise InvalidPayableError("version must be a positive integer.")
        self._validate_installments()
        self._validate_state_metadata()

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        number: str,
        supplier_id: UUID,
        supplier_tax_id: str,
        created_by: UUID,
        nominal_amount: Decimal,
        installment_plan: tuple[tuple[date, Decimal], ...],
        interest_amount: Decimal = Decimal("0.00"),
        discount_amount: Decimal = Decimal("0.00"),
        surcharge_amount: Decimal = Decimal("0.00"),
        currency: str = "BRL",
        provisional_entry_id: UUID | None = None,
    ) -> Payable:
        payable_id = uuid4()
        installments = tuple(
            PayableInstallment.create(
                company_id=company_id,
                payable_id=payable_id,
                number=index,
                due_date=due_date,
                amount=amount,
            )
            for index, (due_date, amount) in enumerate(installment_plan, start=1)
        )
        return cls(
            id=payable_id,
            company_id=company_id,
            number=number,
            supplier_id=supplier_id,
            supplier_tax_id=supplier_tax_id,
            provisional_entry_id=provisional_entry_id,
            currency=currency,
            nominal_amount=nominal_amount,
            interest_amount=interest_amount,
            discount_amount=discount_amount,
            surcharge_amount=surcharge_amount,
            status=PayableStatus.DRAFT,
            installments=installments,
            created_by=created_by,
            decision_by=None,
            decision_reason=None,
            version=1,
        )

    @property
    def total_amount(self) -> Decimal:
        return (
            self.nominal_amount
            + self.interest_amount
            + self.surcharge_amount
            - self.discount_amount
        ).quantize(_CENT)

    @property
    def paid_amount(self) -> Decimal:
        return sum(
            (
                installment.amount
                for installment in self.installments
                if installment.status is PayableInstallmentStatus.PAID
            ),
            Decimal("0.00"),
        )

    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.paid_amount

    def submit_for_approval(self) -> Payable:
        if self.status is not PayableStatus.DRAFT:
            raise InvalidPayableStateError("only draft payables can be submitted for approval.")
        return replace(
            self,
            status=PayableStatus.PENDING_APPROVAL,
            version=self.version + 1,
        )

    def approve(
        self,
        *,
        approver_id: UUID,
        policy: PayableSegregationPolicy,
    ) -> Payable:
        if self.status is not PayableStatus.PENDING_APPROVAL:
            raise InvalidPayableStateError("only pending payables can be approved.")
        if not isinstance(policy, PayableSegregationPolicy):
            raise InvalidPayableError("policy must be a PayableSegregationPolicy.")
        approver = _uuid(approver_id, "approver_id")
        policy.require_distinct_approver(
            created_by=self.created_by,
            approver_id=approver,
            amount=self.total_amount,
        )
        return replace(
            self,
            status=PayableStatus.APPROVED,
            decision_by=approver,
            version=self.version + 1,
        )

    def reject(self, *, rejected_by: UUID, reason: str) -> Payable:
        if self.status is not PayableStatus.PENDING_APPROVAL:
            raise InvalidPayableStateError("only pending payables can be rejected.")
        return replace(
            self,
            status=PayableStatus.REJECTED,
            decision_by=_uuid(rejected_by, "rejected_by"),
            decision_reason=_text(reason, "decision_reason", maximum=500),
            version=self.version + 1,
        )

    def schedule(self, schedule_ids: tuple[UUID, ...]) -> Payable:
        if self.status is not PayableStatus.APPROVED:
            raise InvalidPayableStateError("only approved payables can be scheduled.")
        if len(schedule_ids) != len(self.installments) or len(set(schedule_ids)) != len(
            schedule_ids
        ):
            raise InstallmentMismatchError(
                "schedule_ids must contain one unique id for each installment."
            )
        installments = tuple(
            installment.schedule(schedule_id)
            for installment, schedule_id in zip(self.installments, schedule_ids, strict=True)
        )
        return replace(
            self,
            status=PayableStatus.SCHEDULED,
            installments=installments,
            version=self.version + 1,
        )

    def mark_installment_paid(
        self,
        *,
        installment_number: int,
        paid_on: date,
        payment_reference: str,
    ) -> Payable:
        if self.status is not PayableStatus.SCHEDULED:
            raise InvalidPayableStateError(
                "only scheduled payables can register installment payment."
            )
        selected = next(
            (
                installment
                for installment in self.installments
                if installment.number == installment_number
            ),
            None,
        )
        if selected is None:
            raise InstallmentMismatchError("installment_number does not belong to the payable.")
        installments = tuple(
            installment.mark_paid(
                paid_on=paid_on,
                payment_reference=payment_reference,
            )
            if installment.number == installment_number
            else installment
            for installment in self.installments
        )
        status = (
            PayableStatus.PAID
            if all(
                installment.status is PayableInstallmentStatus.PAID for installment in installments
            )
            else PayableStatus.SCHEDULED
        )
        return replace(
            self,
            status=status,
            installments=installments,
            version=self.version + 1,
        )

    def cancel_from_source(self, *, cancelled_by: UUID, reason: str) -> Payable:
        """Reject an unpaid obligation and release pending payment schedules."""
        if self.status in {PayableStatus.REJECTED, PayableStatus.PAID} or any(
            item.status is PayableInstallmentStatus.PAID for item in self.installments
        ):
            raise InvalidPayableStateError("paid or rejected payables cannot be source-cancelled.")
        return replace(
            self,
            status=PayableStatus.REJECTED,
            installments=tuple(item.release_schedule() for item in self.installments),
            decision_by=_uuid(cancelled_by, "cancelled_by"),
            decision_reason=_text(reason, "decision_reason", maximum=500),
            version=self.version + 1,
        )

    def _validate_installments(self) -> None:
        if not self.installments:
            raise InstallmentMismatchError("payable requires at least one installment.")
        if any(not isinstance(item, PayableInstallment) for item in self.installments):
            raise InstallmentMismatchError("all installments must be validated entities.")
        if any(
            item.company_id != self.company_id or item.payable_id != self.id
            for item in self.installments
        ):
            raise InstallmentMismatchError(
                "installments must belong to the same payable and company."
            )
        expected_numbers = tuple(range(1, len(self.installments) + 1))
        if tuple(item.number for item in self.installments) != expected_numbers:
            raise InstallmentMismatchError("installment numbers must be sequential and ordered.")
        installment_total = sum((item.amount for item in self.installments), Decimal("0.00"))
        if installment_total != self.total_amount:
            raise InstallmentMismatchError(
                "installment total must equal the payable amount after adjustments."
            )

    def _validate_state_metadata(self) -> None:
        if self.status in {PayableStatus.DRAFT, PayableStatus.PENDING_APPROVAL}:
            if self.decision_by is not None or self.decision_reason is not None:
                raise InvalidPayableError("undecided payables cannot contain decision metadata.")
            if any(item.status is not PayableInstallmentStatus.OPEN for item in self.installments):
                raise InvalidPayableError("undecided payables require open installments.")
            return
        if self.decision_by is None:
            raise InvalidPayableError("decided payables require decision_by.")
        _uuid(self.decision_by, "decision_by")
        if self.status is PayableStatus.REJECTED:
            object.__setattr__(
                self,
                "decision_reason",
                _text(self.decision_reason or "", "decision_reason", maximum=500),
            )
            if any(item.status is not PayableInstallmentStatus.OPEN for item in self.installments):
                raise InvalidPayableError("rejected payables require open installments.")
            return
        if self.decision_reason is not None:
            raise InvalidPayableError("approved payables cannot contain a rejection reason.")
        if self.status is PayableStatus.APPROVED:
            if any(item.status is not PayableInstallmentStatus.OPEN for item in self.installments):
                raise InvalidPayableError("approved payables require open installments.")
            return
        if self.status is PayableStatus.SCHEDULED:
            if any(
                item.status
                not in {
                    PayableInstallmentStatus.SCHEDULED,
                    PayableInstallmentStatus.PAID,
                }
                for item in self.installments
            ) or all(item.status is PayableInstallmentStatus.PAID for item in self.installments):
                raise InvalidPayableError(
                    "scheduled payables require at least one scheduled installment."
                )
            return
        if any(item.status is not PayableInstallmentStatus.PAID for item in self.installments):
            raise InvalidPayableError("paid payables require every installment to be paid.")


__all__ = [
    "Payable",
    "PayableInstallment",
    "PayableInstallmentStatus",
    "PayableStatus",
]

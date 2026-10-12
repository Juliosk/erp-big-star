"""HTTP contracts for M12 payables."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.finance.application import PayableAuditEntry, PayableDetail, PayablePage
from erp.modules.finance.domain import Payable, ProvisionalFinancialEntry


class InstallmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_date: date
    amount: Decimal = Field(gt=0, decimal_places=2)


class CreatePayableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    number: str = Field(min_length=1, max_length=64)
    supplier_id: UUID
    supplier_tax_id: str = Field(min_length=11, max_length=32)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    nominal_amount: Decimal = Field(gt=0, decimal_places=2)
    interest_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    surcharge_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    installments: list[InstallmentRequest] = Field(min_length=1, max_length=120)


class SchedulePayableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_ids: list[UUID] = Field(min_length=1, max_length=120)


class AdjustPayableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discount_amount: Decimal = Field(ge=0, decimal_places=2)
    surcharge_amount: Decimal = Field(ge=0, decimal_places=2)


class PayableInstallmentResponse(BaseModel):
    id: UUID
    number: int
    due_date: date
    amount: Decimal
    status: str
    schedule_id: UUID | None
    paid_on: date | None
    payment_reference: str | None


class PayableResponse(BaseModel):
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
    total_amount: Decimal
    outstanding_amount: Decimal
    status: str
    created_by: UUID
    decision_by: UUID | None
    decision_reason: str | None
    version: int
    installments: list[PayableInstallmentResponse]

    @classmethod
    def from_domain(cls, value: Payable) -> PayableResponse:
        return cls(
            id=value.id,
            company_id=value.company_id,
            number=value.number,
            supplier_id=value.supplier_id,
            supplier_tax_id=value.supplier_tax_id,
            provisional_entry_id=value.provisional_entry_id,
            currency=value.currency,
            nominal_amount=value.nominal_amount,
            interest_amount=value.interest_amount,
            discount_amount=value.discount_amount,
            surcharge_amount=value.surcharge_amount,
            total_amount=value.total_amount,
            outstanding_amount=value.outstanding_amount,
            status=value.status.value,
            created_by=value.created_by,
            decision_by=value.decision_by,
            decision_reason=value.decision_reason,
            version=value.version,
            installments=[
                PayableInstallmentResponse(
                    id=item.id,
                    number=item.number,
                    due_date=item.due_date,
                    amount=item.amount,
                    status=item.status.value,
                    schedule_id=item.schedule_id,
                    paid_on=item.paid_on,
                    payment_reference=item.payment_reference,
                )
                for item in value.installments
            ],
        )


class ProvisionalEntryResponse(BaseModel):
    id: UUID
    origin: str
    source_id: UUID
    source_version: int
    amount: Decimal
    currency: str
    status: str
    version: int

    @classmethod
    def from_domain(cls, value: ProvisionalFinancialEntry) -> ProvisionalEntryResponse:
        return cls(
            id=value.id,
            origin=value.origin.value,
            source_id=value.source_id,
            source_version=value.source_version,
            amount=value.amount,
            currency=value.currency,
            status=value.status.value,
            version=value.version,
        )


class AuditEntryResponse(BaseModel):
    id: UUID
    operation: str
    occurred_at: datetime
    actor_user_id: UUID | None
    reason_code: str | None
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None

    @classmethod
    def from_application(cls, value: PayableAuditEntry) -> AuditEntryResponse:
        return cls(
            id=value.id,
            operation=value.operation,
            occurred_at=value.occurred_at,
            actor_user_id=value.actor_user_id,
            reason_code=value.reason_code,
            before_snapshot=value.before_snapshot,
            after_snapshot=value.after_snapshot,
        )


class PayableDetailResponse(PayableResponse):
    provisional_entry: ProvisionalEntryResponse | None
    audit_history: list[AuditEntryResponse]

    @classmethod
    def from_detail(cls, value: PayableDetail) -> PayableDetailResponse:
        payload = PayableResponse.from_domain(value.payable).model_dump()
        return cls(
            **payload,
            provisional_entry=(
                None
                if value.provisional_entry is None
                else ProvisionalEntryResponse.from_domain(value.provisional_entry)
            ),
            audit_history=[
                AuditEntryResponse.from_application(item) for item in value.audit_history
            ],
        )


class PageMeta(BaseModel):
    page: int
    page_size: int
    has_more: bool


class PayableListResponse(BaseModel):
    data: list[PayableResponse]
    meta: PageMeta

    @classmethod
    def from_page(cls, value: PayablePage) -> PayableListResponse:
        return cls(
            data=[PayableResponse.from_domain(item) for item in value.items],
            meta=PageMeta(page=value.page, page_size=value.page_size, has_more=value.has_more),
        )


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]

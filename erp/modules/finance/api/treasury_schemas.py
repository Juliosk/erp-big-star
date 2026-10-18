"""HTTP schemas for the M12 Treasury payment-batch API."""

import base64
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.finance.application import (
    RemittanceArtifact,
    TreasuryAuditEntry,
    TreasuryBatchDetail,
    TreasuryBatchMutation,
    TreasuryBatchPage,
    TreasuryBatchReview,
    TreasuryReturnResult,
)
from erp.modules.finance.domain import PaymentBatch


class BeneficiaryBankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_code: str = Field(min_length=3, max_length=3)
    branch_number: str = Field(min_length=1, max_length=5)
    account_number: str = Field(min_length=1, max_length=20)
    account_digit: str = Field(min_length=1, max_length=2)
    account_type: str
    holder_name: str = Field(min_length=1, max_length=120)
    holder_tax_id: str = Field(min_length=11, max_length=18)


class TreasuryInstallmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installment_id: UUID
    beneficiary: BeneficiaryBankRequest


class CreateTreasuryBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=1, max_length=40)
    treasury_account_id: UUID
    scheduled_date: date
    remittance_format: str
    execution_mode: str
    installments: list[TreasuryInstallmentRequest] = Field(min_length=1, max_length=500)


class RemittanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_instance_id: UUID | None = None


class TreasuryBatchItemResponse(BaseModel):
    id: UUID
    payable_id: UUID
    installment_id: UUID
    supplier_id: UUID
    amount: Decimal
    currency: str
    due_date: date
    matching_session_id: UUID
    beneficiary_bank_code: str
    beneficiary_account_masked: str
    beneficiary_holder_name: str


class TreasuryBatchReviewResponse(BaseModel):
    status: str
    blocked: bool
    revision: int
    required_since: datetime
    last_event_at: datetime
    source_states: dict[str, object]
    reasons: list[dict[str, object]]

    @classmethod
    def from_application(cls, value: TreasuryBatchReview) -> TreasuryBatchReviewResponse:
        return cls(
            status=value.status,
            blocked=value.blocked,
            revision=value.revision,
            required_since=value.required_since,
            last_event_at=value.last_event_at,
            source_states=value.source_states,
            reasons=list(value.reasons),
        )


class TreasuryBatchResponse(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    treasury_account_id: UUID
    scheduled_date: date
    currency: str
    total_amount: Decimal
    remittance_format: str
    execution_mode: str
    status: str
    version: int
    approved_by: UUID | None
    released_by: UUID | None
    submission_protocol: str | None
    submitted_at: datetime | None
    transition_reason: str | None
    bank_confirmation_protocol: str | None
    bank_failure_protocol: str | None
    bank_failure_status: str | None
    items: list[TreasuryBatchItemResponse]
    review: TreasuryBatchReviewResponse | None = None

    @classmethod
    def from_domain(
        cls,
        value: PaymentBatch,
        review: TreasuryBatchReview | None = None,
    ) -> TreasuryBatchResponse:
        confirmation = value.bank_confirmation
        failure = value.bank_failure
        return cls(
            id=value.id,
            company_id=value.company_id,
            code=value.code,
            treasury_account_id=value.treasury_account_id,
            scheduled_date=value.scheduled_date,
            currency=value.currency,
            total_amount=value.total_amount,
            remittance_format=value.remittance_format.value,
            execution_mode=value.execution_mode.value,
            status=value.status.value,
            version=value.version,
            approved_by=value.approved_by,
            released_by=value.released_by,
            submission_protocol=value.submission_protocol,
            submitted_at=value.submitted_at,
            transition_reason=value.transition_reason,
            bank_confirmation_protocol=(None if confirmation is None else confirmation.protocol),
            bank_failure_protocol=None if failure is None else failure.protocol,
            bank_failure_status=None if failure is None else failure.status_code,
            items=[
                TreasuryBatchItemResponse(
                    id=item.id,
                    payable_id=item.payable_id,
                    installment_id=item.installment_id,
                    supplier_id=item.supplier_id,
                    amount=item.amount,
                    currency=item.currency,
                    due_date=item.due_date,
                    matching_session_id=item.matching_session_id,
                    beneficiary_bank_code=item.beneficiary.bank_code,
                    beneficiary_account_masked=f"***{item.beneficiary.account_number[-4:]}",
                    beneficiary_holder_name=item.beneficiary.holder_name,
                )
                for item in value.items
            ],
            review=(
                None if review is None else TreasuryBatchReviewResponse.from_application(review)
            ),
        )


class RemittanceArtifactResponse(BaseModel):
    filename: str
    media_type: str
    checksum_sha256: str
    record_count: int
    total_amount: Decimal
    dry_run: bool
    content_base64: str

    @classmethod
    def from_application(cls, value: RemittanceArtifact) -> RemittanceArtifactResponse:
        return cls(
            filename=value.filename,
            media_type=value.media_type,
            checksum_sha256=value.checksum_sha256,
            record_count=value.record_count,
            total_amount=value.total_amount,
            dry_run=value.dry_run,
            content_base64=base64.b64encode(value.content).decode("ascii"),
        )


class TreasuryMutationResponse(BaseModel):
    batch: TreasuryBatchResponse
    workflow_instance_id: UUID | None
    remittance: RemittanceArtifactResponse | None

    @classmethod
    def from_application(cls, value: TreasuryBatchMutation) -> TreasuryMutationResponse:
        return cls(
            batch=TreasuryBatchResponse.from_domain(value.batch),
            workflow_instance_id=value.workflow_instance_id,
            remittance=(
                None
                if value.remittance is None
                else RemittanceArtifactResponse.from_application(value.remittance)
            ),
        )


class TreasuryAuditEntryResponse(BaseModel):
    id: UUID
    from_status: str | None
    to_status: str
    aggregate_version: int
    actor_id: UUID
    occurred_at: datetime
    details: dict[str, object]

    @classmethod
    def from_application(cls, value: TreasuryAuditEntry) -> TreasuryAuditEntryResponse:
        return cls(
            id=value.id,
            from_status=value.from_status,
            to_status=value.to_status,
            aggregate_version=value.aggregate_version,
            actor_id=value.actor_id,
            occurred_at=value.occurred_at,
            details=value.details,
        )


class TreasuryBatchDetailResponse(BaseModel):
    batch: TreasuryBatchResponse
    audit_history: list[TreasuryAuditEntryResponse]

    @classmethod
    def from_application(cls, value: TreasuryBatchDetail) -> TreasuryBatchDetailResponse:
        return cls(
            batch=TreasuryBatchResponse.from_domain(value.batch, value.review),
            audit_history=[
                TreasuryAuditEntryResponse.from_application(item) for item in value.audit_history
            ],
        )


class PageMeta(BaseModel):
    page: int
    page_size: int
    has_more: bool


class TreasuryBatchListResponse(BaseModel):
    data: list[TreasuryBatchResponse]
    meta: PageMeta

    @classmethod
    def from_application(cls, value: TreasuryBatchPage) -> TreasuryBatchListResponse:
        reviews = dict(value.reviews)
        return cls(
            data=[
                TreasuryBatchResponse.from_domain(item, reviews.get(item.id))
                for item in value.items
            ],
            meta=PageMeta(
                page=value.page,
                page_size=value.page_size,
                has_more=value.has_more,
            ),
        )


class BankSettlementResponse(BaseModel):
    payment_batch_id: UUID
    status: str
    version: int
    replayed: bool


class TreasuryReturnResponse(BaseModel):
    settlements: list[BankSettlementResponse]

    @classmethod
    def from_application(cls, value: TreasuryReturnResult) -> TreasuryReturnResponse:
        return cls(
            settlements=[
                BankSettlementResponse(
                    payment_batch_id=item.batch.id,
                    status=item.batch.status.value,
                    version=item.batch.version,
                    replayed=item.replayed,
                )
                for item in value.settlements
            ]
        )


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]

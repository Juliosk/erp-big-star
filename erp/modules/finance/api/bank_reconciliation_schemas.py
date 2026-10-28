"""Pydantic contracts for bank-reconciliation endpoints."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from erp.modules.finance.application import (
    BankConciliationResult,
    BankMatchMode,
    BankMovementEntry,
    BankMovementPage,
    BankResolutionMode,
    BankStatementPage,
)
from erp.modules.finance.domain import BankMovement, BankStatement


class MatchStatementRequest(BaseModel):
    mode: BankMatchMode = BankMatchMode.SIMULATE


class ResolveMovementRequest(BaseModel):
    mode: BankResolutionMode
    candidate_id: UUID | None = None
    justification: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_resolution(self) -> ResolveMovementRequest:
        if self.mode in {
            BankResolutionMode.ACCEPT_MATCH,
            BankResolutionMode.FORCE_MATCH,
        } and self.candidate_id is None:
            raise ValueError("candidate_id is required for match resolutions.")
        if self.mode is BankResolutionMode.DIRECT_ENTRY and self.candidate_id is not None:
            raise ValueError("candidate_id is forbidden for direct entries.")
        return self


class BankMovementResponse(BaseModel):
    id: UUID
    external_id: str
    booked_on: date
    amount: Decimal
    direction: str
    kind: str
    description: str
    document_number: str | None
    status: str
    matched_reference_id: UUID | None
    reconciled_at: datetime | None
    match_score: Decimal | None

    @classmethod
    def from_domain(cls, value: BankMovement) -> BankMovementResponse:
        return cls(
            id=value.id,
            external_id=value.external_id,
            booked_on=value.booked_on,
            amount=value.amount,
            direction=value.direction.value,
            kind=value.kind.value,
            description=value.description,
            document_number=value.document_number,
            status=value.status.value,
            matched_reference_id=value.matched_reference_id,
            reconciled_at=value.reconciled_at,
            match_score=value.match_score,
        )


class BankStatementResponse(BaseModel):
    id: UUID
    company_id: UUID
    bank_account_id: UUID
    bank_code: str
    account_reference: str
    period_start: date
    period_end: date
    imported_at: datetime
    source: str
    source_hash: str
    status: str
    movement_count: int
    pending_count: int
    reconciled_count: int
    version: int

    @classmethod
    def from_domain(cls, value: BankStatement) -> BankStatementResponse:
        reconciled = sum(item.status.value == "RECONCILED" for item in value.movements)
        return cls(
            id=value.id,
            company_id=value.company_id,
            bank_account_id=value.bank_account_id,
            bank_code=value.bank_code,
            account_reference=value.account_reference,
            period_start=value.period_start,
            period_end=value.period_end,
            imported_at=value.imported_at,
            source=value.source.value,
            source_hash=value.source_hash,
            status=value.status.value,
            movement_count=len(value.movements),
            pending_count=len(value.movements) - reconciled,
            reconciled_count=reconciled,
            version=value.version,
        )


class BankStatementDetailResponse(BaseModel):
    statement: BankStatementResponse
    movements: list[BankMovementResponse]

    @classmethod
    def from_domain(cls, value: BankStatement) -> BankStatementDetailResponse:
        return cls(
            statement=BankStatementResponse.from_domain(value),
            movements=[BankMovementResponse.from_domain(item) for item in value.movements],
        )


class BankStatementListResponse(BaseModel):
    data: list[BankStatementResponse]
    page: int
    page_size: int
    has_more: bool

    @classmethod
    def from_page(cls, value: BankStatementPage) -> BankStatementListResponse:
        return cls(
            data=[BankStatementResponse.from_domain(item) for item in value.items],
            page=value.page,
            page_size=value.page_size,
            has_more=value.has_more,
        )


class BankMovementListResponse(BaseModel):
    statement_id: UUID
    data: list[BankMovementResponse]


class BankMovementQueueItemResponse(BankMovementResponse):
    statement_id: UUID

    @classmethod
    def from_entry(cls, value: BankMovementEntry) -> BankMovementQueueItemResponse:
        return cls(
            statement_id=value.statement_id,
            **BankMovementResponse.from_domain(value.movement).model_dump(),
        )


class BankMovementQueueResponse(BaseModel):
    data: list[BankMovementQueueItemResponse]
    page: int
    page_size: int
    has_more: bool

    @classmethod
    def from_page(cls, value: BankMovementPage) -> BankMovementQueueResponse:
        return cls(
            data=[BankMovementQueueItemResponse.from_entry(item) for item in value.items],
            page=value.page,
            page_size=value.page_size,
            has_more=value.has_more,
        )


class BankConciliationOutcomeResponse(BaseModel):
    movement_id: UUID
    classification: str
    reason: str | None
    candidate_id: UUID | None
    candidate_source: str | None
    candidate_count: int


class BankConciliationResponse(BaseModel):
    statement: BankStatementResponse
    outcomes: list[BankConciliationOutcomeResponse]
    reconciled_count: int

    @classmethod
    def from_application(cls, value: BankConciliationResult) -> BankConciliationResponse:
        return cls(
            statement=BankStatementResponse.from_domain(value.statement),
            outcomes=[
                BankConciliationOutcomeResponse(
                    movement_id=item.movement_id,
                    classification=item.classification.value,
                    reason=None if item.reason is None else item.reason.value,
                    candidate_id=item.candidate_id,
                    candidate_source=(
                        None if item.candidate_source is None else item.candidate_source.value
                    ),
                    candidate_count=item.candidate_count,
                )
                for item in value.outcomes
            ],
            reconciled_count=value.reconciled_count,
        )


__all__ = [
    "BankConciliationResponse",
    "BankMovementListResponse",
    "BankMovementQueueResponse",
    "BankMovementResponse",
    "BankStatementDetailResponse",
    "BankStatementListResponse",
    "BankStatementResponse",
    "MatchStatementRequest",
    "ResolveMovementRequest",
]

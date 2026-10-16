"""HTTP contracts for explainable M6 three-way matching sessions."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.procurement.application.matching_governance import (
    MatchingGovernanceResult,
    MatchingOverrideDecision,
)
from erp.modules.procurement.application.matching_sessions import (
    MatchingAuditEntry,
    MatchingSessionDetail,
    MatchingSessionPage,
)
from erp.modules.procurement.domain import (
    LineMatchResult,
    ThreeWayMatchLine,
    ThreeWayMatchSession,
)


class MatchingLineReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_key: str = Field(min_length=1, max_length=64)
    purchase_order_item_id: UUID
    goods_receipt_item_id: UUID
    fiscal_document_item_id: UUID


class MatchingToleranceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_price_variance_percentage: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    quantity_variance_percentage: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    rounding_absolute_limit: Decimal = Field(default=Decimal("0.01"), ge=0, le=1)
    version: int = Field(default=1, ge=1)


class CreateMatchingSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    purchase_order_id: UUID
    goods_receipt_ids: list[UUID] = Field(min_length=1, max_length=500)
    inbound_fiscal_document_ids: list[UUID] = Field(min_length=1, max_length=500)
    provisional_entry_id: UUID
    payable_id: UUID | None = None
    tolerance: MatchingToleranceRequest = Field(default_factory=MatchingToleranceRequest)
    lines: list[MatchingLineReferenceRequest] = Field(min_length=1, max_length=500)


class RequestMatchingOverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    justification: str = Field(min_length=10, max_length=500)


class DecideMatchingOverrideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_instance_id: UUID
    workflow_step_instance_id: UUID
    workflow_expected_version: int = Field(ge=1)
    decision: MatchingOverrideDecision
    reason: str = Field(min_length=10, max_length=500)


class ArtifactReferenceResponse(BaseModel):
    id: UUID
    version: int


class MatchingSnapshotResponse(BaseModel):
    purchase_order: ArtifactReferenceResponse
    goods_receipts: list[ArtifactReferenceResponse]
    fiscal_documents: list[ArtifactReferenceResponse]
    provisional_entry: ArtifactReferenceResponse
    payable: ArtifactReferenceResponse | None
    supplier_id: UUID
    currency: str
    purchase_order_total_amount: Decimal
    invoiced_total_amount: Decimal
    obligation_amount: Decimal
    captured_at: datetime


class MatchingLineResponse(BaseModel):
    match_key: str
    purchase_order_item_id: UUID
    goods_receipt_item_id: UUID
    fiscal_document_item_id: UUID
    ordered_quantity: Decimal
    received_quantity: Decimal
    invoiced_quantity: Decimal
    ordered_unit_price: Decimal
    invoiced_unit_price: Decimal
    currency: str
    result_status: str | None
    quantity_delta: Decimal | None
    unit_price_delta: Decimal | None
    allowed_quantity_delta: Decimal | None
    allowed_unit_price_delta: Decimal | None
    reasons: list[str]


class MatchingToleranceResponse(BaseModel):
    unit_price_variance_percentage: Decimal
    quantity_variance_percentage: Decimal
    rounding_absolute_limit: Decimal
    version: int


class MatchingSessionResponse(BaseModel):
    id: UUID
    company_id: UUID
    status: str
    version: int
    created_by: UUID
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    report_status: str | None
    snapshot: MatchingSnapshotResponse
    tolerance: MatchingToleranceResponse
    lines: list[MatchingLineResponse]

    @classmethod
    def from_domain(cls, value: ThreeWayMatchSession) -> MatchingSessionResponse:
        results = (
            {item.line.match_key: item for item in value.report.lines}
            if value.report is not None
            else {}
        )
        purchase = value.purchase_order_snapshot
        receiving = value.receiving_fiscal_snapshot
        financial = value.financial_snapshot
        return cls(
            id=value.id,
            company_id=value.company_id,
            status=value.status,
            version=value.version,
            created_by=value.created_by,
            created_at=value.created_at,
            started_at=value.started_at,
            completed_at=value.completed_at,
            report_status=value.report.status if value.report is not None else None,
            snapshot=MatchingSnapshotResponse(
                purchase_order=ArtifactReferenceResponse(
                    id=purchase.purchase_order.id,
                    version=purchase.purchase_order.version,
                ),
                goods_receipts=[
                    ArtifactReferenceResponse(id=item.id, version=item.version)
                    for item in receiving.goods_receipts
                ],
                fiscal_documents=[
                    ArtifactReferenceResponse(id=item.id, version=item.version)
                    for item in receiving.fiscal_documents
                ],
                provisional_entry=ArtifactReferenceResponse(
                    id=financial.provisional_entry.id,
                    version=financial.provisional_entry.version,
                ),
                payable=ArtifactReferenceResponse(
                    id=financial.payable.id,
                    version=financial.payable.version,
                )
                if financial.payable is not None
                else None,
                supplier_id=purchase.supplier_id,
                currency=purchase.currency,
                purchase_order_total_amount=purchase.total_amount,
                invoiced_total_amount=receiving.invoiced_total_amount,
                obligation_amount=financial.obligation_amount,
                captured_at=max(
                    purchase.captured_at,
                    receiving.captured_at,
                    financial.captured_at,
                ),
            ),
            tolerance=MatchingToleranceResponse(
                unit_price_variance_percentage=(
                    value.tolerance_policy.unit_price_variance_percentage
                ),
                quantity_variance_percentage=(value.tolerance_policy.quantity_variance_percentage),
                rounding_absolute_limit=value.tolerance_policy.rounding_absolute_limit,
                version=value.tolerance_policy.version,
            ),
            lines=[_line_response(line, results.get(line.match_key)) for line in value.lines],
        )


class MatchingAuditResponse(BaseModel):
    id: UUID
    from_status: str | None
    to_status: str
    aggregate_version: int
    actor_id: UUID
    occurred_at: datetime
    details: dict[str, object]

    @classmethod
    def from_entry(cls, value: MatchingAuditEntry) -> MatchingAuditResponse:
        return cls(
            id=value.id,
            from_status=value.from_status,
            to_status=value.to_status,
            aggregate_version=value.aggregate_version,
            actor_id=value.actor_id,
            occurred_at=value.occurred_at,
            details=value.details,
        )


class MatchingSessionDetailResponse(BaseModel):
    session: MatchingSessionResponse
    audit_history: list[MatchingAuditResponse]

    @classmethod
    def from_detail(cls, value: MatchingSessionDetail) -> MatchingSessionDetailResponse:
        return cls(
            session=MatchingSessionResponse.from_domain(value.session),
            audit_history=[MatchingAuditResponse.from_entry(item) for item in value.audit_history],
        )


class MatchingExecutionResponse(BaseModel):
    session: MatchingSessionResponse
    event_ids: list[UUID]


class MatchingWorkflowStepResponse(BaseModel):
    id: UUID
    sequence: int
    code: str
    name: str
    required_permission: str
    status: str
    version: int


class MatchingWorkflowResponse(BaseModel):
    id: UUID
    status: str
    version: int
    discrepancy_amount: Decimal
    requested_by: UUID
    steps: list[MatchingWorkflowStepResponse]


class MatchingGovernanceResponse(BaseModel):
    session: MatchingSessionResponse
    workflow: MatchingWorkflowResponse
    event_ids: list[UUID]

    @classmethod
    def from_result(cls, value: MatchingGovernanceResult) -> MatchingGovernanceResponse:
        return cls(
            session=MatchingSessionResponse.from_domain(value.session),
            workflow=MatchingWorkflowResponse(
                id=value.workflow.id,
                status=value.workflow.status,
                version=value.workflow.version,
                discrepancy_amount=value.workflow.discrepancy_amount,
                requested_by=value.workflow.requested_by,
                steps=[
                    MatchingWorkflowStepResponse(
                        id=step.id,
                        sequence=step.sequence,
                        code=step.code,
                        name=step.name,
                        required_permission=step.required_permission,
                        status=step.status,
                        version=step.version,
                    )
                    for step in value.workflow.steps
                ],
            ),
            event_ids=list(value.event_ids),
        )


class MatchingPageMeta(BaseModel):
    page: int
    page_size: int
    has_more: bool


class MatchingSessionListResponse(BaseModel):
    data: list[MatchingSessionResponse]
    meta: MatchingPageMeta

    @classmethod
    def from_page(cls, value: MatchingSessionPage) -> MatchingSessionListResponse:
        return cls(
            data=[MatchingSessionResponse.from_domain(item) for item in value.items],
            meta=MatchingPageMeta(
                page=value.page,
                page_size=value.page_size,
                has_more=value.has_more,
            ),
        )


def _line_response(
    line: ThreeWayMatchLine,
    result: LineMatchResult | None,
) -> MatchingLineResponse:
    return MatchingLineResponse(
        match_key=line.match_key,
        purchase_order_item_id=line.purchase_order_item_id,
        goods_receipt_item_id=line.goods_receipt_item_id,
        fiscal_document_item_id=line.fiscal_document_item_id,
        ordered_quantity=_six_decimals(line.ordered_quantity),
        received_quantity=_six_decimals(line.received_quantity),
        invoiced_quantity=_six_decimals(line.invoiced_quantity),
        ordered_unit_price=_six_decimals(line.ordered_unit_price),
        invoiced_unit_price=_six_decimals(line.invoiced_unit_price),
        currency=line.currency,
        result_status=result.status if result is not None else None,
        quantity_delta=_six_decimals(result.quantity_delta) if result is not None else None,
        unit_price_delta=_six_decimals(result.unit_price_delta) if result is not None else None,
        allowed_quantity_delta=(
            _six_decimals(result.allowed_quantity_delta) if result is not None else None
        ),
        allowed_unit_price_delta=(
            _six_decimals(result.allowed_unit_price_delta) if result is not None else None
        ),
        reasons=list(result.reasons) if result is not None else [],
    )


def _six_decimals(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]

"""Pure purchase requisition aggregate owned by M6 Procurement."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.procurement.domain.approval import ApprovalRequest, ApprovalSubjectType
from erp.modules.procurement.domain.exceptions import (
    InvalidProcurementTransitionError,
    InvalidRequisitionError,
    ProcurementDomainError,
)
from erp.modules.procurement.domain.support import identifier, quantity, require_uuid, text


class RequisitionStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RequisitionUrgency(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class RequisitionItem:
    id: UUID
    company_id: UUID
    requisition_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_of_measure: str
    needed_by: date
    urgency: RequisitionUrgency
    specification: str

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        requisition_id: UUID,
        product_id: UUID,
        quantity_value: Decimal | str | int,
        unit_of_measure: str,
        needed_by: date,
        urgency: RequisitionUrgency = RequisitionUrgency.NORMAL,
        specification: str,
    ) -> RequisitionItem:
        if not isinstance(needed_by, date):
            raise InvalidRequisitionError("needed_by must be a date.")
        if needed_by < datetime.now(UTC).date():
            raise InvalidRequisitionError("needed_by cannot be in the past.")
        if not isinstance(urgency, RequisitionUrgency):
            raise InvalidRequisitionError("urgency must be an official M6 urgency.")
        try:
            return cls(
                id=uuid4(),
                company_id=require_uuid(company_id, "company_id"),
                requisition_id=require_uuid(requisition_id, "requisition_id"),
                product_id=require_uuid(product_id, "product_id"),
                quantity=quantity(quantity_value),
                unit_of_measure=identifier(unit_of_measure, "unit_of_measure", maximum=16),
                needed_by=needed_by,
                urgency=urgency,
                specification=text(specification, "specification", maximum=1000),
            )
        except ProcurementDomainError as error:
            raise InvalidRequisitionError(str(error)) from error


@dataclass(frozen=True, slots=True)
class PurchaseRequisition:
    id: UUID
    company_id: UUID
    number: str
    requester_id: UUID
    cost_center_id: UUID
    status: RequisitionStatus
    items: tuple[RequisitionItem, ...]
    justification: str
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        number: str,
        requester_id: UUID,
        cost_center_id: UUID,
        justification: str,
        lines: tuple[
            tuple[
                UUID,
                Decimal | str | int,
                str,
                date,
                RequisitionUrgency,
                str,
            ],
            ...,
        ],
    ) -> PurchaseRequisition:
        if not lines:
            raise InvalidRequisitionError("purchase requisition requires at least one item.")
        try:
            requisition_id = uuid4()
            items = tuple(
                RequisitionItem.create(
                    company_id=company_id,
                    requisition_id=requisition_id,
                    product_id=product_id,
                    quantity_value=item_quantity,
                    unit_of_measure=unit_of_measure,
                    needed_by=needed_by,
                    urgency=urgency,
                    specification=specification,
                )
                for (
                    product_id,
                    item_quantity,
                    unit_of_measure,
                    needed_by,
                    urgency,
                    specification,
                ) in lines
            )
            if len({item.product_id for item in items}) != len(items):
                raise InvalidRequisitionError(
                    "a product can appear only once in a purchase requisition."
                )
            return cls(
                id=requisition_id,
                company_id=require_uuid(company_id, "company_id"),
                number=identifier(number, "number"),
                requester_id=require_uuid(requester_id, "requester_id"),
                cost_center_id=require_uuid(cost_center_id, "cost_center_id"),
                status=RequisitionStatus.DRAFT,
                items=items,
                justification=text(justification, "justification", maximum=1000),
                version=1,
            )
        except ProcurementDomainError as error:
            if isinstance(error, InvalidRequisitionError):
                raise
            raise InvalidRequisitionError(str(error)) from error

    @property
    def deadline(self) -> date:
        return min(item.needed_by for item in self.items)

    @property
    def urgency(self) -> RequisitionUrgency:
        priority = {
            RequisitionUrgency.LOW: 0,
            RequisitionUrgency.NORMAL: 1,
            RequisitionUrgency.HIGH: 2,
            RequisitionUrgency.CRITICAL: 3,
        }
        return max((item.urgency for item in self.items), key=priority.__getitem__)

    def submit(self) -> PurchaseRequisition:
        if self.status is not RequisitionStatus.DRAFT:
            raise InvalidProcurementTransitionError("only draft requisitions can be submitted.")
        return replace(self, status=RequisitionStatus.SUBMITTED, version=self.version + 1)

    def approve(self) -> PurchaseRequisition:
        if self.status is not RequisitionStatus.SUBMITTED:
            raise InvalidProcurementTransitionError("only submitted requisitions can be approved.")
        return replace(self, status=RequisitionStatus.APPROVED, version=self.version + 1)

    def reject(self) -> PurchaseRequisition:
        if self.status is not RequisitionStatus.SUBMITTED:
            raise InvalidProcurementTransitionError("only submitted requisitions can be rejected.")
        return replace(self, status=RequisitionStatus.REJECTED, version=self.version + 1)

    def cancel(self) -> PurchaseRequisition:
        if self.status not in {
            RequisitionStatus.DRAFT,
            RequisitionStatus.SUBMITTED,
            RequisitionStatus.APPROVED,
        }:
            raise InvalidProcurementTransitionError("only active requisitions can be cancelled.")
        return replace(self, status=RequisitionStatus.CANCELLED, version=self.version + 1)

    def approval_request(
        self, *, estimated_amount: Decimal | str | int, currency: str
    ) -> ApprovalRequest:
        if self.status is not RequisitionStatus.SUBMITTED:
            raise InvalidProcurementTransitionError(
                "only submitted requisitions can request approval."
            )
        return ApprovalRequest(
            company_id=self.company_id,
            subject_type=ApprovalSubjectType.PURCHASE_REQUISITION,
            subject_id=self.id,
            requested_by=self.requester_id,
            amount=Decimal(str(estimated_amount)),
            currency=currency,
            aggregate_version=self.version,
        )


__all__ = [
    "PurchaseRequisition",
    "RequisitionItem",
    "RequisitionStatus",
    "RequisitionUrgency",
]

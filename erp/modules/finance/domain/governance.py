"""Pure governance projection for M12 payable approval and divergence gates."""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.finance.domain.exceptions import (
    InvalidPayableError,
    InvalidPayableStateError,
    PayableDivergenceBlockedError,
)


class PayableApprovalStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class PayableGovernance:
    company_id: UUID
    payable_id: UUID
    fiscal_blocked: bool = False
    purchasing_blocked: bool = False
    approval_status: PayableApprovalStatus = PayableApprovalStatus.NOT_REQUESTED
    workflow_instance_id: UUID | None = None
    authority_limit: Decimal | None = None
    sod_threshold: Decimal = Decimal("0.01")
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.company_id, UUID) or self.company_id.int == 0:
            raise InvalidPayableError("governance.company_id must be a non-zero UUID.")
        if not isinstance(self.payable_id, UUID) or self.payable_id.int == 0:
            raise InvalidPayableError("governance.payable_id must be a non-zero UUID.")
        if not isinstance(self.approval_status, PayableApprovalStatus):
            raise InvalidPayableError("governance approval_status is invalid.")
        if self.workflow_instance_id is not None and not isinstance(
            self.workflow_instance_id, UUID
        ):
            raise InvalidPayableError("workflow_instance_id must be a UUID.")
        for name, amount in (
            ("authority_limit", self.authority_limit),
            ("sod_threshold", self.sod_threshold),
        ):
            if amount is not None and (
                not isinstance(amount, Decimal)
                or not amount.is_finite()
                or amount < Decimal("0.00")
                or amount.quantize(Decimal("0.01")) != amount
            ):
                raise InvalidPayableError(f"{name} must be non-negative money.")
        if self.version < 1:
            raise InvalidPayableError("governance.version must be positive.")

    @property
    def blocked(self) -> bool:
        return self.fiscal_blocked or self.purchasing_blocked

    def require_unblocked(self) -> None:
        if self.blocked:
            raise PayableDivergenceBlockedError(
                "unresolved fiscal or purchasing divergence blocks this payable."
            )

    def apply_divergence(
        self, *, fiscal_blocked: bool, purchasing_blocked: bool
    ) -> PayableGovernance:
        return replace(
            self,
            fiscal_blocked=fiscal_blocked,
            purchasing_blocked=purchasing_blocked,
            version=self.version + 1,
        )

    def request_approval(
        self,
        *,
        workflow_instance_id: UUID | None,
        authority_limit: Decimal | None,
        sod_threshold: Decimal,
    ) -> PayableGovernance:
        self.require_unblocked()
        if self.approval_status is not PayableApprovalStatus.NOT_REQUESTED:
            raise InvalidPayableStateError("payable approval was already requested.")
        return replace(
            self,
            approval_status=(
                PayableApprovalStatus.PENDING
                if workflow_instance_id is not None
                else PayableApprovalStatus.APPROVED
            ),
            workflow_instance_id=workflow_instance_id,
            authority_limit=authority_limit,
            sod_threshold=sod_threshold,
            version=self.version + 1,
        )

    def decide(self, *, approved: bool, workflow_instance_id: UUID) -> PayableGovernance:
        if self.approval_status is not PayableApprovalStatus.PENDING:
            raise InvalidPayableStateError("payable governance is not pending approval.")
        if self.workflow_instance_id != workflow_instance_id:
            raise InvalidPayableError("workflow decision does not match the payable request.")
        return replace(
            self,
            approval_status=(
                PayableApprovalStatus.APPROVED if approved else PayableApprovalStatus.REJECTED
            ),
            version=self.version + 1,
        )


__all__ = ["PayableApprovalStatus", "PayableGovernance"]

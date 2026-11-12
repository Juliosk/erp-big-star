"""Application service for governed M12 payment-request approvals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from erp.modules.finance.application.treasury import TreasuryCommandMetadata
from erp.modules.finance.domain import (
    InvalidPaymentRequestError,
    PaymentApprovalAuthority,
    PaymentRequest,
    TreasuryVersionConflictError,
)
from erp.platform.errors import ApplicationError

PAYMENT_REQUEST_SUBMITTED = "PaymentRequestSubmitted"
PAYMENT_REQUEST_APPROVED = "PaymentRequestApproved"
PAYMENT_REQUEST_REJECTED = "PaymentRequestRejected"


@dataclass(frozen=True, slots=True)
class ChangePaymentRequest:
    company_id: UUID
    payment_request_id: UUID
    expected_version: int
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class PaymentRequestMutationResult:
    request: PaymentRequest
    event_id: UUID
    audit_id: UUID


class PaymentRequestStore(Protocol):
    async def get_for_update(self, request_id: UUID) -> PaymentRequest | None: ...

    async def save(
        self,
        request: PaymentRequest,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentRequest: ...


class PaymentApprovalAuthorityProvider(Protocol):
    """Resolve trusted tenant-specific approval ceilings for one actor."""

    async def authority_for(
        self,
        *,
        company_id: UUID,
        actor_id: UUID,
        currency: str,
    ) -> PaymentApprovalAuthority | None: ...


class PaymentRequestEffectsPort(Protocol):
    async def record(
        self,
        *,
        before: PaymentRequest,
        after: PaymentRequest,
        event_type: str,
        actor_id: UUID,
        metadata: TreasuryCommandMetadata,
    ) -> tuple[UUID, UUID]: ...


class PaymentRequestApplicationService:
    """Coordinate workflow submission and trusted multi-tier approval limits."""

    def __init__(
        self,
        repository: PaymentRequestStore,
        authorities: PaymentApprovalAuthorityProvider,
        effects: PaymentRequestEffectsPort,
    ) -> None:
        self._repository = repository
        self._authorities = authorities
        self._effects = effects

    async def submit(
        self,
        command: ChangePaymentRequest,
        *,
        actor_id: UUID,
        workflow_instance_id: UUID,
    ) -> PaymentRequestMutationResult:
        current = await self._load(command)
        pending = current.submit(workflow_instance_id=workflow_instance_id)
        return await self._persist(
            current,
            pending,
            actor_id=actor_id,
            event_type=PAYMENT_REQUEST_SUBMITTED,
            metadata=command.metadata,
        )

    async def approve(
        self,
        command: ChangePaymentRequest,
        *,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> PaymentRequestMutationResult:
        current = await self._load(command)
        authority = await self._authorities.authority_for(
            company_id=current.company_id,
            actor_id=actor_id,
            currency=current.currency,
        )
        if authority is None or authority.actor_id != actor_id:
            raise InvalidPaymentRequestError(
                "Actor has no trusted approval authority for this payment request."
            )
        approved = current.approve(authority=authority, occurred_at=occurred_at)
        return await self._persist(
            current,
            approved,
            actor_id=actor_id,
            event_type=PAYMENT_REQUEST_APPROVED,
            metadata=command.metadata,
        )

    async def reject(
        self,
        command: ChangePaymentRequest,
        *,
        actor_id: UUID,
        occurred_at: datetime,
        reason: str,
    ) -> PaymentRequestMutationResult:
        current = await self._load(command)
        rejected = current.reject(
            actor_id=actor_id,
            occurred_at=occurred_at,
            reason=reason,
        )
        return await self._persist(
            current,
            rejected,
            actor_id=actor_id,
            event_type=PAYMENT_REQUEST_REJECTED,
            metadata=command.metadata,
        )

    async def _load(self, command: ChangePaymentRequest) -> PaymentRequest:
        _validate_change(command)
        current = await self._repository.get_for_update(command.payment_request_id)
        if current is None or current.company_id != command.company_id:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Payment request not found.",
                status_code=404,
            )
        if current.version != command.expected_version:
            raise TreasuryVersionConflictError(
                f"Payment request expected version {command.expected_version} is stale."
            )
        return current

    async def _persist(
        self,
        before: PaymentRequest,
        after: PaymentRequest,
        *,
        actor_id: UUID,
        event_type: str,
        metadata: TreasuryCommandMetadata,
    ) -> PaymentRequestMutationResult:
        saved = await self._repository.save(
            after,
            actor_id=actor_id,
            expected_version=before.version,
        )
        event_id, audit_id = await self._effects.record(
            before=before,
            after=saved,
            event_type=event_type,
            actor_id=actor_id,
            metadata=metadata,
        )
        return PaymentRequestMutationResult(saved, event_id, audit_id)


def _validate_change(command: ChangePaymentRequest) -> None:
    if not isinstance(command, ChangePaymentRequest):
        raise TypeError("command must be a ChangePaymentRequest.")
    for value, field_name in (
        (command.company_id, "company_id"),
        (command.payment_request_id, "payment_request_id"),
    ):
        if not isinstance(value, UUID) or value.int == 0:
            raise ValueError(f"{field_name} must be a non-zero UUID.")
    if (
        not isinstance(command.expected_version, int)
        or isinstance(command.expected_version, bool)
        or command.expected_version < 1
    ):
        raise ValueError("expected_version must be a positive integer.")


__all__ = [
    "PAYMENT_REQUEST_APPROVED",
    "PAYMENT_REQUEST_REJECTED",
    "PAYMENT_REQUEST_SUBMITTED",
    "ChangePaymentRequest",
    "PaymentApprovalAuthorityProvider",
    "PaymentRequestApplicationService",
    "PaymentRequestEffectsPort",
    "PaymentRequestMutationResult",
    "PaymentRequestStore",
]

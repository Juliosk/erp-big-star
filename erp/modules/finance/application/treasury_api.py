"""Public application facade for tenant-scoped M12 Treasury HTTP use cases."""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.application.permissions import (
    FINANCE_TREASURY_BATCH_CREATE,
    FINANCE_TREASURY_BATCH_EXECUTE,
    FINANCE_TREASURY_READ,
    FinanceAuthorization,
)
from erp.modules.finance.application.settlement import PaymentSettlementResult
from erp.modules.finance.application.treasury import RemittanceArtifact, TreasuryCommandMetadata
from erp.modules.finance.domain import (
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    PaymentBatch,
    PaymentBatchStatus,
    PaymentExecutionMode,
)
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class TreasuryInstallmentInput:
    installment_id: UUID
    beneficiary: BeneficiaryBankAccount


@dataclass(frozen=True, slots=True)
class CreateTreasuryBatch:
    company_id: UUID
    code: str
    treasury_account_id: UUID
    scheduled_date: date
    remittance_format: BankRemittanceFormat
    execution_mode: PaymentExecutionMode
    installments: tuple[TreasuryInstallmentInput, ...]
    idempotency_key: str
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "code": self.code,
            "treasury_account_id": str(self.treasury_account_id),
            "scheduled_date": self.scheduled_date.isoformat(),
            "remittance_format": self.remittance_format.value,
            "execution_mode": self.execution_mode.value,
            "installments": [
                {
                    "installment_id": str(item.installment_id),
                    "bank_code": item.beneficiary.bank_code,
                    "branch_number": item.beneficiary.branch_number,
                    "account_number": item.beneficiary.account_number,
                    "account_digit": item.beneficiary.account_digit,
                    "account_type": item.beneficiary.account_type.value,
                    "holder_name": item.beneficiary.holder_name,
                    "holder_tax_id": item.beneficiary.holder_tax_id,
                }
                for item in self.installments
            ],
        }


@dataclass(frozen=True, slots=True)
class ChangeTreasuryBatch:
    company_id: UUID
    payment_batch_id: UUID
    expected_version: int
    idempotency_key: str
    workflow_instance_id: UUID | None = None
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "payment_batch_id": str(self.payment_batch_id),
            "expected_version": self.expected_version,
            "workflow_instance_id": (
                None if self.workflow_instance_id is None else str(self.workflow_instance_id)
            ),
        }


@dataclass(frozen=True, slots=True)
class ProcessTreasuryReturn:
    company_id: UUID
    remittance_format: BankRemittanceFormat
    content: bytes
    idempotency_key: str
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "remittance_format": self.remittance_format.value,
            "content_sha256": hashlib.sha256(self.content).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class TreasuryBatchMutation:
    batch: PaymentBatch
    remittance: RemittanceArtifact | None = None
    workflow_instance_id: UUID | None = None
    idempotency_replayed: bool = False


@dataclass(frozen=True, slots=True)
class TreasuryReturnResult:
    settlements: tuple[PaymentSettlementResult, ...]
    idempotency_replayed: bool = False


@dataclass(frozen=True, slots=True)
class TreasuryAuditEntry:
    id: UUID
    from_status: str | None
    to_status: str
    aggregate_version: int
    actor_id: UUID
    occurred_at: datetime
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class TreasuryBatchReview:
    status: str
    blocked: bool
    revision: int
    required_since: datetime
    last_event_at: datetime
    source_states: dict[str, object]
    reasons: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class TreasuryBatchDetail:
    batch: PaymentBatch
    audit_history: tuple[TreasuryAuditEntry, ...]
    review: TreasuryBatchReview | None = None


@dataclass(frozen=True, slots=True)
class TreasuryBatchPage:
    items: tuple[PaymentBatch, ...]
    page: int
    page_size: int
    has_more: bool
    reviews: tuple[tuple[UUID, TreasuryBatchReview], ...] = ()


class TreasuryStore(Protocol):
    async def create(
        self, command: CreateTreasuryBatch, *, actor_id: UUID
    ) -> TreasuryBatchMutation: ...

    async def dry_run(
        self, command: ChangeTreasuryBatch, *, actor_id: UUID
    ) -> TreasuryBatchMutation: ...

    async def remittance(
        self, command: ChangeTreasuryBatch, *, actor_id: UUID
    ) -> TreasuryBatchMutation: ...

    async def process_return(
        self, command: ProcessTreasuryReturn, *, actor_id: UUID
    ) -> TreasuryReturnResult: ...

    async def get(self, company_id: UUID, batch_id: UUID) -> TreasuryBatchDetail | None: ...

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PaymentBatchStatus | None,
        scheduled_from: date | None,
        scheduled_to: date | None,
    ) -> TreasuryBatchPage: ...


class TreasuryApplicationService:
    def __init__(self, store: TreasuryStore, authorization: FinanceAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreateTreasuryBatch
    ) -> TreasuryBatchMutation:
        await self._authorization.require(
            context, command.company_id, FINANCE_TREASURY_BATCH_CREATE, write=True
        )
        return await self._store.create(command, actor_id=context.principal.user_id)

    async def dry_run(
        self, context: SecurityContext, command: ChangeTreasuryBatch
    ) -> TreasuryBatchMutation:
        await self._authorization.require(
            context, command.company_id, FINANCE_TREASURY_BATCH_CREATE, write=True
        )
        return await self._store.dry_run(command, actor_id=context.principal.user_id)

    async def remittance(
        self, context: SecurityContext, command: ChangeTreasuryBatch
    ) -> TreasuryBatchMutation:
        await self._authorization.require(
            context, command.company_id, FINANCE_TREASURY_BATCH_EXECUTE, write=True
        )
        return await self._store.remittance(command, actor_id=context.principal.user_id)

    async def process_return(
        self, context: SecurityContext, command: ProcessTreasuryReturn
    ) -> TreasuryReturnResult:
        await self._authorization.require(
            context, command.company_id, FINANCE_TREASURY_BATCH_EXECUTE, write=True
        )
        return await self._store.process_return(command, actor_id=context.principal.user_id)


class TreasuryQueryService:
    def __init__(self, store: TreasuryStore, authorization: FinanceAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def get(
        self,
        context: SecurityContext,
        company_id: UUID,
        batch_id: UUID,
    ) -> TreasuryBatchDetail:
        await self._authorization.require(context, company_id, FINANCE_TREASURY_READ)
        value = await self._store.get(company_id, batch_id)
        if value is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Payment batch not found.",
                status_code=404,
            )
        return value

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PaymentBatchStatus | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
    ) -> TreasuryBatchPage:
        await self._authorization.require(context, company_id, FINANCE_TREASURY_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR",
                message="Invalid pagination.",
                status_code=422,
            )
        if (
            scheduled_from is not None
            and scheduled_to is not None
            and scheduled_from > scheduled_to
        ):
            raise ApplicationError(
                code="VALIDATION_ERROR",
                message="scheduled_from must not exceed scheduled_to.",
                status_code=422,
            )
        return await self._store.list(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            scheduled_from=scheduled_from,
            scheduled_to=scheduled_to,
        )


__all__ = [name for name in globals() if not name.startswith("_")]

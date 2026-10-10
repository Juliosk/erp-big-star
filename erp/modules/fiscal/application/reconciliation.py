"""Framework-free fiscal and physical receiving reconciliation use cases."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.application.permissions import FISCAL_INBOUND_MANAGE, FiscalAuthorization


class ReconciliationStatus(StrEnum):
    DIVERGENT = "DIVERGENT"
    POSTED = "POSTED"


class ReconciliationIssueKind(StrEnum):
    SUPPLIER_MISMATCH = "SUPPLIER_MISMATCH"
    LINE_MAPPING_MISMATCH = "LINE_MAPPING_MISMATCH"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    UNIT_PRICE_MISMATCH = "UNIT_PRICE_MISMATCH"
    FISCAL_TOTAL_MISMATCH = "FISCAL_TOTAL_MISMATCH"
    SPECIFICATION_MISMATCH = "SPECIFICATION_MISMATCH"
    INSPECTION_NOT_APPROVED = "INSPECTION_NOT_APPROVED"

    @property
    def blocks_financial(self) -> bool:
        return self in {
            ReconciliationIssueKind.SUPPLIER_MISMATCH,
            ReconciliationIssueKind.UNIT_PRICE_MISMATCH,
            ReconciliationIssueKind.FISCAL_TOTAL_MISMATCH,
        }

    @property
    def blocks_physical(self) -> bool:
        return self in {
            ReconciliationIssueKind.LINE_MAPPING_MISMATCH,
            ReconciliationIssueKind.QUANTITY_MISMATCH,
            ReconciliationIssueKind.SPECIFICATION_MISMATCH,
            ReconciliationIssueKind.INSPECTION_NOT_APPROVED,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationLineMapping:
    inbound_line_number: int
    receipt_item_id: UUID

    def __post_init__(self) -> None:
        if self.inbound_line_number < 1 or not isinstance(self.receipt_item_id, UUID):
            raise ValueError("A reconciliation line mapping requires a positive line and UUID.")


@dataclass(frozen=True, slots=True)
class ReconciliationIssue:
    kind: ReconciliationIssueKind
    message: str
    inbound_line_number: int | None = None
    receipt_item_id: UUID | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True, slots=True)
class FiscalReceivingReconciliation:
    id: UUID
    company_id: UUID
    inbound_fiscal_document_id: UUID
    goods_receipt_id: UUID
    purchase_order_id: UUID
    status: ReconciliationStatus
    issues: tuple[ReconciliationIssue, ...]
    financial_blocked: bool
    physical_pending: bool
    inventory_transaction_ids: tuple[UUID, ...]
    version: int
    reconciled_at: datetime


@dataclass(frozen=True, slots=True)
class ReconciliationMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None

    @classmethod
    def new(cls) -> ReconciliationMetadata:
        return cls(uuid4(), uuid4())


@dataclass(frozen=True, slots=True)
class ReconcileFiscalReceiving:
    company_id: UUID
    inbound_fiscal_document_id: UUID
    goods_receipt_id: UUID
    expected_inbound_version: int
    line_mappings: tuple[ReconciliationLineMapping, ...]
    idempotency_key: str
    price_tolerance: Decimal = Decimal("0.01")
    metadata: ReconciliationMetadata = field(default_factory=ReconciliationMetadata.new)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    reconciliation: FiscalReceivingReconciliation
    idempotency_replayed: bool = False


class FiscalReceivingReconciliationOperations(Protocol):
    async def reconcile(
        self, command: ReconcileFiscalReceiving, *, actor_id: UUID
    ) -> ReconciliationResult: ...

    async def get(
        self, company_id: UUID, inbound_document_id: UUID
    ) -> FiscalReceivingReconciliation | None: ...


class FiscalReceivingReconciliationService:
    def __init__(
        self,
        operations: FiscalReceivingReconciliationOperations,
        authorization: FiscalAuthorization,
    ) -> None:
        self._operations = operations
        self._authorization = authorization

    async def reconcile(
        self, context: SecurityContext, command: ReconcileFiscalReceiving
    ) -> ReconciliationResult:
        await self._authorization.require(
            context, command.company_id, FISCAL_INBOUND_MANAGE, write=True
        )
        return await self._operations.reconcile(command, actor_id=context.principal.user_id)

    async def get(
        self, context: SecurityContext, company_id: UUID, inbound_document_id: UUID
    ) -> FiscalReceivingReconciliation | None:
        await self._authorization.require(context, company_id, FISCAL_INBOUND_MANAGE)
        return await self._operations.get(company_id, inbound_document_id)


__all__ = [
    "FiscalReceivingReconciliation",
    "FiscalReceivingReconciliationOperations",
    "FiscalReceivingReconciliationService",
    "ReconcileFiscalReceiving",
    "ReconciliationIssue",
    "ReconciliationIssueKind",
    "ReconciliationLineMapping",
    "ReconciliationMetadata",
    "ReconciliationResult",
    "ReconciliationStatus",
]

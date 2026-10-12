"""Framework-neutral M12 payable use cases and ports."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.application.permissions import (
    FINANCE_PAYABLE_ADJUST,
    FINANCE_PAYABLE_CREATE,
    FINANCE_PAYABLE_READ,
    FinanceAuthorization,
)
from erp.modules.finance.domain import Payable, PayableStatus, ProvisionalFinancialEntry
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class PayableCommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None

    @classmethod
    def new(cls) -> PayableCommandMetadata:
        return cls(uuid4(), uuid4())


@dataclass(frozen=True, slots=True)
class InstallmentInput:
    due_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class CreatePayable:
    company_id: UUID
    number: str
    supplier_id: UUID
    supplier_tax_id: str
    nominal_amount: Decimal
    installments: tuple[InstallmentInput, ...]
    idempotency_key: str
    currency: str = "BRL"
    interest_amount: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    surcharge_amount: Decimal = Decimal("0.00")
    metadata: PayableCommandMetadata = field(default_factory=PayableCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "number": self.number,
            "supplier_id": str(self.supplier_id),
            "supplier_tax_id": self.supplier_tax_id,
            "currency": self.currency,
            "nominal_amount": str(self.nominal_amount),
            "interest_amount": str(self.interest_amount),
            "discount_amount": str(self.discount_amount),
            "surcharge_amount": str(self.surcharge_amount),
            "installments": [
                {"due_date": value.due_date.isoformat(), "amount": str(value.amount)}
                for value in self.installments
            ],
        }


@dataclass(frozen=True, slots=True)
class ChangePayable:
    company_id: UUID
    payable_id: UUID
    expected_version: int
    metadata: PayableCommandMetadata = field(default_factory=PayableCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class AdjustPayable(ChangePayable):
    discount_amount: Decimal = Decimal("0.00")
    surcharge_amount: Decimal = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class SchedulePayable(ChangePayable):
    schedule_ids: tuple[UUID, ...] = ()
    idempotency_key: str = ""

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "payable_id": str(self.payable_id),
            "expected_version": self.expected_version,
            "schedule_ids": [str(value) for value in self.schedule_ids],
        }


@dataclass(frozen=True, slots=True)
class PayableMutationResult:
    payable: Payable
    idempotency_replayed: bool = False


@dataclass(frozen=True, slots=True)
class PayableAuditEntry:
    id: UUID
    operation: str
    occurred_at: datetime
    actor_user_id: UUID | None
    reason_code: str | None
    before_snapshot: dict[str, object] | None
    after_snapshot: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class PayableDetail:
    payable: Payable
    provisional_entry: ProvisionalFinancialEntry | None
    audit_history: tuple[PayableAuditEntry, ...]


@dataclass(frozen=True, slots=True)
class PayablePage:
    items: tuple[Payable, ...]
    page: int
    page_size: int
    has_more: bool


class PayableStore(Protocol):
    async def create(self, command: CreatePayable, *, actor_id: UUID) -> PayableMutationResult: ...
    async def submit(
        self,
        command: ChangePayable,
        *,
        actor_id: UUID,
        granted_permissions: frozenset[str],
    ) -> Payable: ...
    async def adjust(self, command: AdjustPayable, *, actor_id: UUID) -> Payable: ...
    async def schedule(
        self, command: SchedulePayable, *, actor_id: UUID
    ) -> PayableMutationResult: ...
    async def get(self, company_id: UUID, payable_id: UUID) -> PayableDetail | None: ...
    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        supplier_id: UUID | None,
        status: PayableStatus | None,
        created_from: datetime | None,
        created_to: datetime | None,
        due_from: date | None,
        due_to: date | None,
    ) -> PayablePage: ...


class PayableApplicationService:
    def __init__(self, store: PayableStore, authorization: FinanceAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreatePayable
    ) -> PayableMutationResult:
        await self._authorization.require(
            context, command.company_id, FINANCE_PAYABLE_CREATE, write=True
        )
        return await self._store.create(command, actor_id=context.principal.user_id)

    async def submit(self, context: SecurityContext, command: ChangePayable) -> Payable:
        await self._authorization.require(
            context, command.company_id, FINANCE_PAYABLE_CREATE, write=True
        )
        return await self._store.submit(
            command,
            actor_id=context.principal.user_id,
            granted_permissions=frozenset(str(value) for value in context.permissions),
        )

    async def adjust(self, context: SecurityContext, command: AdjustPayable) -> Payable:
        await self._authorization.require(
            context, command.company_id, FINANCE_PAYABLE_ADJUST, write=True
        )
        return await self._store.adjust(command, actor_id=context.principal.user_id)

    async def schedule(
        self, context: SecurityContext, command: SchedulePayable
    ) -> PayableMutationResult:
        await self._authorization.require(
            context, command.company_id, FINANCE_PAYABLE_ADJUST, write=True
        )
        return await self._store.schedule(command, actor_id=context.principal.user_id)

    async def get(
        self, context: SecurityContext, company_id: UUID, payable_id: UUID
    ) -> PayableDetail:
        await self._authorization.require(context, company_id, FINANCE_PAYABLE_READ)
        value = await self._store.get(company_id, payable_id)
        if value is None:
            raise _not_found()
        return value

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        supplier_id: UUID | None = None,
        status: PayableStatus | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        due_from: date | None = None,
        due_to: date | None = None,
    ) -> PayablePage:
        await self._authorization.require(context, company_id, FINANCE_PAYABLE_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise _validation("Invalid pagination.")
        if created_from is not None and created_to is not None and created_from > created_to:
            raise _validation("created_from must not exceed created_to.")
        if due_from is not None and due_to is not None and due_from > due_to:
            raise _validation("due_from must not exceed due_to.")
        return await self._store.list(
            company_id,
            page=page,
            page_size=page_size,
            supplier_id=supplier_id,
            status=status,
            created_from=created_from,
            created_to=created_to,
            due_from=due_from,
            due_to=due_to,
        )


def _not_found() -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message="Payable not found.", status_code=404
    )


def _validation(message: str) -> ApplicationError:
    return ApplicationError(code="VALIDATION_ERROR", message=message, status_code=422)


__all__ = [name for name in globals() if not name.startswith("_")]

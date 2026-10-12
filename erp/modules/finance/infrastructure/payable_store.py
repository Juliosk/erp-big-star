"""Transactional PostgreSQL adapter for M12 payable use cases."""

from collections.abc import Callable
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.payables import (
    AdjustPayable,
    ChangePayable,
    CreatePayable,
    PayableAuditEntry,
    PayableDetail,
    PayableMutationResult,
    PayablePage,
    SchedulePayable,
)
from erp.modules.finance.domain import (
    FinanceDomainError,
    FinanceVersionConflictError,
    Payable,
    PayableConflictError,
    PayableStatus,
)
from erp.modules.finance.infrastructure.payable_repository import PayableRepository
from erp.modules.finance.infrastructure.provisional_repository import (
    ProvisionalEntryRepository,
)
from erp.platform.audit import AuditEvent, AuditEventModel, AuditService
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService


class PostgresPayableStore:
    """Own transactions across payables, idempotency and immutable audit."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)
        self._audit = AuditService()

    async def create(self, command: CreatePayable, *, actor_id: UUID) -> PayableMutationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation="finance.payable.create",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                return PayableMutationResult(
                    await _replay(session, command.company_id, decision.response_body), True
                )
            try:
                payable = Payable.create(
                    company_id=command.company_id,
                    number=command.number,
                    supplier_id=command.supplier_id,
                    supplier_tax_id=command.supplier_tax_id,
                    created_by=actor_id,
                    nominal_amount=command.nominal_amount,
                    installment_plan=tuple(
                        (value.due_date, value.amount) for value in command.installments
                    ),
                    interest_amount=command.interest_amount,
                    discount_amount=command.discount_amount,
                    surcharge_amount=command.surcharge_amount,
                    currency=command.currency,
                )
                await PayableRepository(session, company_id=command.company_id).add(
                    payable, actor_id=actor_id
                )
            except FinanceDomainError as error:
                raise _domain_error(error) from error
            await self._record(
                session,
                payable=payable,
                actor_id=actor_id,
                operation="PAYABLE_CREATED",
                before=None,
                after=_snapshot(payable),
                command=command,
            )
            await _complete(self._idempotency, session, decision, payable, status=201)
            return PayableMutationResult(payable)

    async def submit(self, command: ChangePayable, *, actor_id: UUID) -> Payable:
        return await self._change(
            command,
            actor_id=actor_id,
            operation="PAYABLE_APPROVAL_REQUESTED",
            transform=lambda value: value.submit_for_approval(),
        )

    async def adjust(self, command: AdjustPayable, *, actor_id: UUID) -> Payable:
        return await self._change(
            command,
            actor_id=actor_id,
            operation="PAYABLE_ADJUSTED",
            transform=lambda value: value.adjust_amounts(
                discount_amount=command.discount_amount,
                surcharge_amount=command.surcharge_amount,
            ),
        )

    async def schedule(self, command: SchedulePayable, *, actor_id: UUID) -> PayableMutationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation="finance.payable.schedule",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                return PayableMutationResult(
                    await _replay(session, command.company_id, decision.response_body), True
                )
            repository = PayableRepository(session, company_id=command.company_id)
            current = await _required(repository, command.payable_id)
            _require_version(current.version, command.expected_version)
            try:
                changed = current.schedule(command.schedule_ids)
                await repository.save(
                    changed, actor_id=actor_id, expected_version=command.expected_version
                )
            except FinanceVersionConflictError as error:
                raise _version_error() from error
            except FinanceDomainError as error:
                raise _domain_error(error) from error
            await self._record(
                session,
                payable=changed,
                actor_id=actor_id,
                operation="PAYABLE_SCHEDULED",
                before=_snapshot(current),
                after=_snapshot(changed),
                command=command,
            )
            await _complete(self._idempotency, session, decision, changed)
            return PayableMutationResult(changed)

    async def get(self, company_id: UUID, payable_id: UUID) -> PayableDetail | None:
        async with self._database.session() as session:
            payable = await PayableRepository(session, company_id=company_id).get(payable_id)
            if payable is None:
                return None
            provision = None
            if payable.provisional_entry_id is not None:
                provision = await ProvisionalEntryRepository(session, company_id=company_id).get(
                    payable.provisional_entry_id
                )
            models = tuple(
                await session.scalars(
                    select(AuditEventModel)
                    .where(
                        AuditEventModel.company_id == company_id,
                        AuditEventModel.module == "finance",
                        AuditEventModel.entity_type == "payable",
                        AuditEventModel.entity_id == payable_id,
                    )
                    .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
                )
            )
            return PayableDetail(
                payable,
                provision,
                tuple(
                    PayableAuditEntry(
                        id=value.id,
                        operation=value.operation,
                        occurred_at=value.occurred_at,
                        actor_user_id=value.actor_user_id,
                        reason_code=value.reason_code,
                        before_snapshot=cast(dict[str, object] | None, value.before_snapshot),
                        after_snapshot=cast(dict[str, object] | None, value.after_snapshot),
                    )
                    for value in models
                ),
            )

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
    ) -> PayablePage:
        async with self._database.session() as session:
            repository = PayableRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            values = await repository.list(
                status=status,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
                due_from=due_from,
                due_to=due_to,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
                due_from=due_from,
                due_to=due_to,
                limit=1,
                offset=offset + page_size,
            )
            return PayablePage(values, page, page_size, bool(more))

    async def _change(
        self,
        command: ChangePayable,
        *,
        actor_id: UUID,
        operation: str,
        transform: Callable[[Payable], Payable],
    ) -> Payable:
        async with self._database.session() as session, session.begin():
            repository = PayableRepository(session, company_id=command.company_id)
            current = await _required(repository, command.payable_id)
            _require_version(current.version, command.expected_version)
            try:
                changed = transform(current)
                await repository.save(
                    changed, actor_id=actor_id, expected_version=command.expected_version
                )
            except FinanceVersionConflictError as error:
                raise _version_error() from error
            except FinanceDomainError as error:
                raise _domain_error(error) from error
            await self._record(
                session,
                payable=changed,
                actor_id=actor_id,
                operation=operation,
                before=_snapshot(current),
                after=_snapshot(changed),
                command=command,
            )
            return changed

    async def _record(
        self,
        session: AsyncSession,
        *,
        payable: Payable,
        actor_id: UUID,
        operation: str,
        before: dict[str, object] | None,
        after: dict[str, object],
        command: CreatePayable | ChangePayable,
    ) -> None:
        await self._audit.record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=payable.company_id,
                branch_id=None,
                module="finance",
                entity_type="payable",
                entity_id=payable.id,
                operation=operation,
                request_id=command.metadata.request_id,
                correlation_id=command.metadata.correlation_id,
                before_snapshot=before,
                after_snapshot=after,
                source_ip=command.metadata.source_ip,
            ),
        )


async def _required(repository: PayableRepository, payable_id: UUID) -> Payable:
    payable = await repository.get(payable_id)
    if payable is None:
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND", message="Payable not found.", status_code=404
        )
    return payable


async def _replay(session: AsyncSession, company_id: UUID, body: dict[str, Any] | None) -> Payable:
    if body is None or "payable_id" not in body:
        raise RuntimeError("Stored payable replay has no payable identity.")
    return await _required(
        PayableRepository(session, company_id=company_id), UUID(str(body["payable_id"]))
    )


async def _complete(
    service: IdempotencyService,
    session: AsyncSession,
    decision: IdempotencyDecision,
    payable: Payable,
    *,
    status: int = 200,
) -> None:
    await service.complete(
        session,
        decision,
        response_status=status,
        response_body={"payable_id": str(payable.id)},
    )


def _scope(company_id: UUID, actor_id: UUID) -> str:
    return f"finance-payable:{company_id}:{actor_id}"


def _require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise _version_error()


def _version_error() -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT",
        message="The resource was changed by another transaction.",
        status_code=409,
    )


def _domain_error(error: FinanceDomainError) -> ApplicationError:
    if isinstance(error, PayableConflictError):
        return ApplicationError(code=error.code, message=str(error), status_code=409)
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid payable operation.",
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


def _snapshot(payable: Payable) -> dict[str, object]:
    return {
        "id": str(payable.id),
        "number": payable.number,
        "supplier_id": str(payable.supplier_id),
        "supplier_tax_id": payable.supplier_tax_id,
        "currency": payable.currency,
        "nominal_amount": str(payable.nominal_amount),
        "interest_amount": str(payable.interest_amount),
        "discount_amount": str(payable.discount_amount),
        "surcharge_amount": str(payable.surcharge_amount),
        "total_amount": str(payable.total_amount),
        "status": payable.status.value,
        "version": payable.version,
        "installments": [
            {
                "id": str(item.id),
                "number": item.number,
                "due_date": item.due_date.isoformat(),
                "amount": str(item.amount),
                "status": item.status.value,
                "schedule_id": None if item.schedule_id is None else str(item.schedule_id),
            }
            for item in payable.installments
        ],
    }


__all__ = ["PostgresPayableStore"]

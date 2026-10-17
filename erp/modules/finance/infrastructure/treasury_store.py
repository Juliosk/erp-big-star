"""Transactional PostgreSQL facade for M12 Treasury API use cases."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    ApprovePaymentBatch,
    ChangePaymentBatch,
    ChangeTreasuryBatch,
    CreatePaymentBatch,
    CreateTreasuryBatch,
    PaymentBatchApprovalGateway,
    PaymentBatchService,
    PaymentCandidateProvider,
    PaymentSettlementResult,
    PaymentSettlementService,
    ProcessTreasuryReturn,
    SubmitPaymentBatch,
    TreasuryAuditEntry,
    TreasuryBatchDetail,
    TreasuryBatchMutation,
    TreasuryBatchPage,
    TreasuryReturnResult,
)
from erp.modules.finance.domain import (
    FinanceDomainError,
    PayableInstallmentPaymentSnapshot,
    PaymentBatch,
    PaymentBatchStatus,
    PaymentExecutionMode,
)
from erp.modules.finance.infrastructure.bank_returns import BankReturnAdapterRegistry
from erp.modules.finance.infrastructure.payable_repository import PayableRepository
from erp.modules.finance.infrastructure.remittance import RemittanceAdapterRegistry
from erp.modules.finance.infrastructure.treasury_events import (
    PostgresPaymentBatchEventPublisher,
)
from erp.modules.finance.infrastructure.treasury_repository import PaymentBatchRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService

ApprovalGatewayFactory = Callable[[AsyncSession], PaymentBatchApprovalGateway]
PaymentCandidateProviderFactory = Callable[
    [AsyncSession, CreateTreasuryBatch], PaymentCandidateProvider
]


class PostgresTreasuryStore:
    """Own transactions spanning batches, M22, settlement and idempotency."""

    def __init__(
        self,
        database: Database,
        *,
        ttl_seconds: int,
        approval_gateway_factory: ApprovalGatewayFactory,
        candidate_provider_factory: PaymentCandidateProviderFactory,
    ) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)
        self._approval_gateway_factory = approval_gateway_factory
        self._candidate_provider_factory = candidate_provider_factory
        self._remittance = RemittanceAdapterRegistry()
        self._returns = BankReturnAdapterRegistry()

    async def create(
        self,
        command: CreateTreasuryBatch,
        *,
        actor_id: UUID,
    ) -> TreasuryBatchMutation:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(
                session,
                command.company_id,
                actor_id,
                "finance.treasury.batch.create",
                command.idempotency_key,
                command.payload(),
            )
            if decision.replayed:
                return await self._replay_mutation(
                    session, command.company_id, decision.response_body
                )
            beneficiaries = {item.installment_id: item.beneficiary for item in command.installments}
            if len(beneficiaries) != len(command.installments):
                raise _validation("Each installment must appear exactly once.")
            repository = PaymentBatchRepository(session, company_id=command.company_id)
            service = self._service(
                session,
                repository,
                self._candidate_provider_factory(session, command),
            )
            try:
                result = await service.create(
                    CreatePaymentBatch(
                        company_id=command.company_id,
                        code=command.code,
                        treasury_account_id=command.treasury_account_id,
                        scheduled_date=command.scheduled_date,
                        remittance_format=command.remittance_format,
                        execution_mode=command.execution_mode,
                        installment_ids=tuple(beneficiaries),
                        metadata=command.metadata,
                    ),
                    actor_id=actor_id,
                )
            except FinanceDomainError as error:
                raise _domain_error(error) from error
            mutation = TreasuryBatchMutation(result.batch)
            await self._complete(session, decision, mutation, status=201)
            return mutation

    async def dry_run(
        self,
        command: ChangeTreasuryBatch,
        *,
        actor_id: UUID,
    ) -> TreasuryBatchMutation:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(
                session,
                command.company_id,
                actor_id,
                "finance.treasury.batch.dry-run",
                command.idempotency_key,
                command.payload(),
            )
            if decision.replayed:
                return await self._replay_mutation(
                    session, command.company_id, decision.response_body
                )
            repository = PaymentBatchRepository(session, company_id=command.company_id)
            batch = await _required_batch(repository, command.payment_batch_id)
            _require_version(batch.version, command.expected_version)
            artifact = self._remittance.generate(batch, dry_run=True)
            mutation = TreasuryBatchMutation(batch, remittance=artifact)
            await self._complete(session, decision, mutation)
            return mutation

    async def remittance(
        self,
        command: ChangeTreasuryBatch,
        *,
        actor_id: UUID,
    ) -> TreasuryBatchMutation:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(
                session,
                command.company_id,
                actor_id,
                "finance.treasury.batch.remittance",
                command.idempotency_key,
                command.payload(),
            )
            if decision.replayed:
                return await self._replay_mutation(
                    session, command.company_id, decision.response_body
                )
            repository = PaymentBatchRepository(session, company_id=command.company_id)
            batch = await _required_batch(repository, command.payment_batch_id)
            _require_version(batch.version, command.expected_version)
            if batch.execution_mode is PaymentExecutionMode.DRY_RUN:
                raise ApplicationError(
                    code="DRY_RUN_BATCH_NOT_EXECUTABLE",
                    message="Use the dry-run endpoint for simulation-only batches.",
                    status_code=409,
                )
            service = self._service(session, repository, _UnusedCandidateProvider())

            if batch.status is PaymentBatchStatus.DRAFT:
                pending = await service.submit_for_approval(
                    ChangePaymentBatch(
                        batch.company_id,
                        batch.id,
                        batch.version,
                        command.metadata,
                    ),
                    actor_id=actor_id,
                )
                mutation = TreasuryBatchMutation(
                    pending.batch,
                    workflow_instance_id=pending.workflow_instance_id,
                )
                await self._complete(session, decision, mutation, status=202)
                return mutation

            workflow_instance_id = command.workflow_instance_id
            if batch.status is PaymentBatchStatus.PENDING_APPROVAL:
                if workflow_instance_id is None:
                    raise _validation("workflow_instance_id is required after M22 approval.")
                approved = await service.approve(
                    ApprovePaymentBatch(
                        company_id=batch.company_id,
                        payment_batch_id=batch.id,
                        expected_version=batch.version,
                        metadata=command.metadata,
                        workflow_instance_id=workflow_instance_id,
                    )
                )
                batch = approved.batch

            artifact = None
            if batch.status is PaymentBatchStatus.APPROVED:
                released = await service.release(
                    ChangePaymentBatch(
                        batch.company_id,
                        batch.id,
                        batch.version,
                        command.metadata,
                    ),
                    actor_id=actor_id,
                )
                batch = released.batch
                artifact = released.remittance
            elif batch.status is PaymentBatchStatus.RELEASED:
                artifact = self._remittance.generate(batch, dry_run=False)
            else:
                raise ApplicationError(
                    code="PAYMENT_BATCH_NOT_RELEASABLE",
                    message="The payment batch is not ready for remittance.",
                    status_code=409,
                )
            assert artifact is not None
            submitted = await PaymentSettlementService(
                repository,
                PayableRepository(session, company_id=command.company_id),
                PostgresPaymentBatchEventPublisher(session),
            ).record_submission(
                SubmitPaymentBatch(
                    company_id=batch.company_id,
                    payment_batch_id=batch.id,
                    expected_version=batch.version,
                    protocol=f"SHA256:{artifact.checksum_sha256}",
                    occurred_at=datetime.now(UTC),
                    metadata=command.metadata,
                ),
                actor_id=actor_id,
            )
            mutation = TreasuryBatchMutation(
                submitted.batch,
                remittance=artifact,
                workflow_instance_id=workflow_instance_id,
            )
            await self._complete(session, decision, mutation)
            return mutation

    async def process_return(
        self,
        command: ProcessTreasuryReturn,
        *,
        actor_id: UUID,
    ) -> TreasuryReturnResult:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(
                session,
                command.company_id,
                actor_id,
                "finance.treasury.return.process",
                command.idempotency_key,
                command.payload(),
            )
            if decision.replayed:
                return await self._replay_returns(
                    session, command.company_id, decision.response_body
                )
            document = self._returns.parse(
                command.remittance_format,
                command.content,
                company_id=command.company_id,
            )
            service = PaymentSettlementService(
                PaymentBatchRepository(session, company_id=command.company_id),
                PayableRepository(session, company_id=command.company_id),
                PostgresPaymentBatchEventPublisher(session),
            )
            settlements = tuple(
                [
                    await service.process(
                        notification,
                        actor_id=actor_id,
                        metadata=command.metadata,
                    )
                    for notification in document.records
                ]
            )
            result = TreasuryReturnResult(settlements)
            await self._idempotency.complete(
                session,
                decision,
                response_status=200,
                response_body={"payment_batch_ids": [str(item.batch.id) for item in settlements]},
            )
            return result

    async def get(
        self,
        company_id: UUID,
        batch_id: UUID,
    ) -> TreasuryBatchDetail | None:
        async with self._database.session() as session:
            repository = PaymentBatchRepository(session, company_id=company_id)
            batch = await repository.get(batch_id)
            if batch is None:
                return None
            audit = await repository.audit_log(batch_id)
            return TreasuryBatchDetail(
                batch,
                tuple(
                    TreasuryAuditEntry(
                        id=item.id,
                        from_status=item.from_status,
                        to_status=item.to_status,
                        aggregate_version=item.aggregate_version,
                        actor_id=item.actor_id,
                        occurred_at=item.occurred_at,
                        details=cast(dict[str, object], item.details),
                    )
                    for item in audit
                ),
            )

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PaymentBatchStatus | None,
        scheduled_from: date | None,
        scheduled_to: date | None,
    ) -> TreasuryBatchPage:
        async with self._database.session() as session:
            repository = PaymentBatchRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(
                status=status,
                scheduled_from=scheduled_from,
                scheduled_to=scheduled_to,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                scheduled_from=scheduled_from,
                scheduled_to=scheduled_to,
                limit=1,
                offset=offset + page_size,
            )
            return TreasuryBatchPage(items, page, page_size, bool(more))

    def _service(
        self,
        session: AsyncSession,
        repository: PaymentBatchRepository,
        candidates: PaymentCandidateProvider,
    ) -> PaymentBatchService:
        return PaymentBatchService(
            repository,
            candidates,
            self._approval_gateway_factory(session),
            self._remittance,
            PostgresPaymentBatchEventPublisher(session),
        )

    async def _begin(
        self,
        session: AsyncSession,
        company_id: UUID,
        actor_id: UUID,
        operation: str,
        key: str,
        payload: dict[str, object],
    ) -> IdempotencyDecision:
        return await self._idempotency.begin(
            session,
            scope=f"finance-treasury:{company_id}:{actor_id}",
            operation=operation,
            key=key,
            payload=payload,
        )

    async def _complete(
        self,
        session: AsyncSession,
        decision: IdempotencyDecision,
        mutation: TreasuryBatchMutation,
        *,
        status: int = 200,
    ) -> None:
        await self._idempotency.complete(
            session,
            decision,
            response_status=status,
            response_body={
                "payment_batch_id": str(mutation.batch.id),
                "workflow_instance_id": (
                    None
                    if mutation.workflow_instance_id is None
                    else str(mutation.workflow_instance_id)
                ),
                "remittance": mutation.remittance is not None,
                "dry_run": (None if mutation.remittance is None else mutation.remittance.dry_run),
            },
        )

    async def _replay_mutation(
        self,
        session: AsyncSession,
        company_id: UUID,
        body: dict[str, Any] | None,
    ) -> TreasuryBatchMutation:
        if body is None or "payment_batch_id" not in body:
            raise RuntimeError("Stored treasury replay has no batch identity.")
        batch = await _required_batch(
            PaymentBatchRepository(session, company_id=company_id),
            UUID(str(body["payment_batch_id"])),
        )
        artifact = None
        if body.get("remittance") is True:
            artifact = self._remittance.generate(batch, dry_run=body.get("dry_run") is True)
        workflow = body.get("workflow_instance_id")
        return TreasuryBatchMutation(
            batch,
            remittance=artifact,
            workflow_instance_id=None if workflow is None else UUID(str(workflow)),
            idempotency_replayed=True,
        )

    async def _replay_returns(
        self,
        session: AsyncSession,
        company_id: UUID,
        body: dict[str, Any] | None,
    ) -> TreasuryReturnResult:
        if body is None or not isinstance(body.get("payment_batch_ids"), list):
            raise RuntimeError("Stored bank-return replay has no batch identities.")
        batches = PaymentBatchRepository(session, company_id=company_id)
        payables = PayableRepository(session, company_id=company_id)
        results: list[PaymentSettlementResult] = []
        for raw_id in body["payment_batch_ids"]:
            batch = await _required_batch(batches, UUID(str(raw_id)))
            payable_values = []
            for payable_id in dict.fromkeys(item.payable_id for item in batch.items):
                payable = await payables.get(payable_id)
                if payable is None:
                    raise RuntimeError("Stored bank-return replay lost its payable.")
                payable_values.append(payable)
            results.append(
                PaymentSettlementResult(batch, tuple(payable_values), None, replayed=True)
            )
        return TreasuryReturnResult(tuple(results), idempotency_replayed=True)


class _UnusedCandidateProvider:
    async def select(
        self,
        *,
        company_id: UUID,
        installment_ids: tuple[UUID, ...],
    ) -> tuple[PayableInstallmentPaymentSnapshot, ...]:
        del company_id, installment_ids
        raise RuntimeError("Candidate selection is unavailable for this command.")


async def _required_batch(
    repository: PaymentBatchRepository,
    batch_id: UUID,
) -> PaymentBatch:
    batch = await repository.get(batch_id)
    if batch is None:
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND",
            message="Payment batch not found.",
            status_code=404,
        )
    return batch


def _require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The payment batch was changed by another transaction.",
            status_code=409,
        )


def _validation(message: str) -> ApplicationError:
    return ApplicationError(code="VALIDATION_ERROR", message=message, status_code=422)


def _domain_error(error: FinanceDomainError) -> ApplicationError:
    return ApplicationError(
        code=error.code,
        message="Invalid treasury operation.",
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = ["PostgresTreasuryStore"]

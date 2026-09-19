"""Atomic M15 quote lifecycle persistence, Audit and Outbox effects."""

from uuid import UUID

from erp.modules.sales.application.lifecycle import (
    ReviseSalesQuote,
    SalesQuoteLifecycleStore,
    SalesQuoteMutationResult,
    TransitionSalesQuote,
)
from erp.modules.sales.application.quotes import SalesQuoteDetail
from erp.modules.sales.domain import QuoteRevision, SalesQuote, SalesQuoteStatus
from erp.modules.sales.infrastructure.repository import SalesQuoteRepository
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class PostgresSalesQuoteLifecycle(SalesQuoteLifecycleStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def revise(
        self, command: ReviseSalesQuote, actor_id: UUID
    ) -> SalesQuoteMutationResult:
        async with self._database.session() as session, session.begin():
            repository = SalesQuoteRepository(session, company_id=command.company_id)
            before = await _required(repository, command.quote_id)
            _version(before, command.expected_version)
            try:
                snapshots = tuple(
                    line.pricing_snapshot_id
                    for line in command.lines
                    if line.pricing_snapshot_id is not None
                )
                changed, revision = before.revise(
                    lines=tuple(
                        (
                            line.product_id,
                            line.quantity,
                            line.unit_price,
                            line.discount_amount,
                        )
                        for line in command.lines
                    ),
                    pricing_snapshot_refs=snapshots,
                )
            except ValueError as error:
                raise _validation(str(error)) from error
            changed = await repository.add_revision(
                changed,
                revision,
                actor_id=actor_id,
                expected_version=command.expected_version,
            )
            event_id, audit_id = await _effects(
                session,
                before,
                changed,
                "SalesQuoteRevised",
                command.metadata,
                actor_id,
                revision,
            )
        return SalesQuoteMutationResult(
            SalesQuoteDetail(changed, (revision,)), event_id, audit_id
        )

    async def transition(
        self, command: TransitionSalesQuote, actor_id: UUID
    ) -> SalesQuoteMutationResult:
        async with self._database.session() as session, session.begin():
            repository = SalesQuoteRepository(session, company_id=command.company_id)
            before = await _required(repository, command.quote_id)
            _version(before, command.expected_version)
            try:
                changed, event_type = _transition(before, command.target_status)
            except ValueError as error:
                raise _validation(str(error)) from error
            changed = await repository.save(changed, actor_id=actor_id)
            event_id, audit_id = await _effects(
                session,
                before,
                changed,
                event_type,
                command.metadata,
                actor_id,
                None,
                command.reason_code,
            )
        return SalesQuoteMutationResult(SalesQuoteDetail(changed, ()), event_id, audit_id)


async def _required(repository: SalesQuoteRepository, quote_id: UUID) -> SalesQuote:
    quote = await repository.get(quote_id)
    if quote is None:
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND", message="Sales quote not found.", status_code=404
        )
    return quote


def _version(quote: SalesQuote, expected: int) -> None:
    if quote.version != expected:
        raise OptimisticLockError(expected_version=expected)


def _transition(quote: SalesQuote, target: SalesQuoteStatus) -> tuple[SalesQuote, str]:
    if target is SalesQuoteStatus.SENT:
        return quote.send(), "SalesQuoteSent"
    if target is SalesQuoteStatus.ACCEPTED:
        return quote.accept(), "SalesQuoteAccepted"
    if target is SalesQuoteStatus.PARTIALLY_ACCEPTED:
        return quote.accept(partial=True), "SalesQuotePartiallyAccepted"
    if target is SalesQuoteStatus.LOST:
        return quote.mark_lost(), "SalesQuoteLost"
    raise ValueError("Unsupported quote transition.")


async def _effects(
    session: object,
    before: SalesQuote,
    after: SalesQuote,
    event_type: str,
    metadata: object,
    actor_id: UUID,
    revision: QuoteRevision | None,
    reason_code: str | None = None,
) -> tuple[UUID, UUID]:
    # Narrow imports and duck-typed arguments keep the transaction helper private.
    from sqlalchemy.ext.asyncio import AsyncSession

    from erp.modules.sales.application.lifecycle import CommandMetadata

    assert isinstance(session, AsyncSession)
    assert isinstance(metadata, CommandMetadata)
    before_snapshot = _snapshot(before)
    after_snapshot = _snapshot(after)
    if revision is not None:
        after_snapshot["revision"] = _revision_snapshot(revision)
    audit_id = await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=after.company_id,
            branch_id=None,
            module="sales",
            entity_type="sales_quote",
            entity_id=after.id,
            operation=event_type,
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
            source_ip=metadata.source_ip,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            reason_code=reason_code,
        ),
    )
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=event_type,
        event_version=1,
        producer_module="sales",
        producer_domain="sales",
        aggregate_type="sales_quote",
        aggregate_id=after.id,
        aggregate_version=after.version,
        company_id=after.company_id,
        branch_id=None,
        correlation_id=metadata.correlation_id,
        request_id=metadata.request_id,
        causation_id=None,
        payload=after_snapshot,
    )
    await OutboxService().enqueue(session, envelope)
    return envelope.message_id, audit_id


def _snapshot(quote: SalesQuote) -> dict[str, object]:
    return {
        "id": str(quote.id),
        "company_id": str(quote.company_id),
        "number": quote.number,
        "customer_id": str(quote.customer_id),
        "seller_id": str(quote.seller_id),
        "currency": quote.currency,
        "status": quote.status,
        "current_revision_number": quote.current_revision_number,
        "workflow_instance_id": str(quote.workflow_instance_id)
        if quote.workflow_instance_id
        else None,
        "converted_order_id": str(quote.converted_order_id) if quote.converted_order_id else None,
        "version": quote.version,
    }


def _revision_snapshot(revision: QuoteRevision) -> dict[str, object]:
    return {
        "id": str(revision.id),
        "revision_number": revision.revision_number,
        "gross_amount": str(revision.gross_amount),
        "discount_amount": str(revision.discount_amount),
        "net_amount": str(revision.net_amount),
    }


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid sales quote lifecycle command.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = ["PostgresSalesQuoteLifecycle"]

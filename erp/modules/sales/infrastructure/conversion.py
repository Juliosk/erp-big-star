"""Atomic, idempotent M15 quote-to-order conversion."""

from uuid import UUID

from erp.modules.sales.application.conversion import (
    ConvertQuoteToOrder,
    SalesOrderConversionResult,
    SalesOrderConversionStore,
)
from erp.modules.sales.domain import SalesOrder, SalesQuoteStatus
from erp.modules.sales.infrastructure.order_repository import SalesOrderRepository
from erp.modules.sales.infrastructure.repository import SalesQuoteRepository
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class PostgresSalesOrderConversion(SalesOrderConversionStore):
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def convert(
        self, command: ConvertQuoteToOrder, actor_id: UUID
    ) -> SalesOrderConversionResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"sales:{command.company_id}:{actor_id}",
                operation="sales.quote.convert-to-order",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            order_repository = SalesOrderRepository(session, company_id=command.company_id)
            if decision.replayed:
                body = decision.response_body or {}
                order_id = UUID(str(body["order_id"]))
                order = await order_repository.get(order_id)
                if order is None:
                    raise RuntimeError("Idempotent sales order replay target is missing.")
                return SalesOrderConversionResult(
                    order=order,
                    quote_version=int(body["quote_version"]),
                    event_id=UUID(str(body["event_id"])),
                    audit_event_id=UUID(str(body["audit_event_id"])),
                    idempotency_replayed=True,
                )

            quote_repository = SalesQuoteRepository(session, company_id=command.company_id)
            quote = await quote_repository.get_for_update(command.quote_id)
            if quote is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Sales quote not found.", status_code=404
                )
            if quote.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            if quote.status not in {
                SalesQuoteStatus.ACCEPTED,
                SalesQuoteStatus.PARTIALLY_ACCEPTED,
            }:
                raise _validation("Only accepted quotes can be converted.")
            revision = await quote_repository.get_revision(
                quote.id, quote.current_revision_number
            )
            if revision is None:
                raise _validation("The current quote revision is missing.")
            snapshots: tuple[UUID | None, ...] = (
                revision.pricing_snapshot_refs
                if revision.pricing_snapshot_refs
                else (None,) * len(revision.items)
            )
            try:
                order = SalesOrder.create_from_quote(
                    company_id=quote.company_id,
                    number=command.order_number,
                    source_quote_id=quote.id,
                    source_quote_revision_number=revision.revision_number,
                    customer_id=quote.customer_id,
                    seller_id=quote.seller_id,
                    currency=quote.currency,
                    lines=tuple(
                        (
                            item.id,
                            item.product_id,
                            item.quantity,
                            item.unit_price,
                            item.discount_amount,
                            snapshot,
                        )
                        for item, snapshot in zip(revision.items, snapshots, strict=True)
                    ),
                )
                converted = quote.convert(order.id)
            except ValueError as error:
                raise _validation(str(error)) from error
            await order_repository.add(order, actor_id=actor_id)
            converted = await quote_repository.save(converted, actor_id=actor_id)
            audit_id = await AuditService().record(
                session,
                AuditEvent(
                    actor_user_id=actor_id,
                    company_id=order.company_id,
                    branch_id=None,
                    module="sales",
                    entity_type="sales_order",
                    entity_id=order.id,
                    operation="SalesOrderCreatedFromQuote",
                    request_id=command.metadata.request_id,
                    correlation_id=command.metadata.correlation_id,
                    source_ip=command.metadata.source_ip,
                    before_snapshot=None,
                    after_snapshot=_order_snapshot(order),
                ),
            )
            envelope = MessageEnvelope.new(
                message_kind=MessageKind.DOMAIN_EVENT,
                message_type="SalesOrderCreatedFromQuote",
                event_version=1,
                producer_module="sales",
                producer_domain="sales",
                aggregate_type="sales_order",
                aggregate_id=order.id,
                aggregate_version=order.version,
                company_id=order.company_id,
                branch_id=None,
                correlation_id=command.metadata.correlation_id,
                request_id=command.metadata.request_id,
                causation_id=None,
                payload=_order_snapshot(order),
            )
            await OutboxService().enqueue(session, envelope)
            response_body: dict[str, object] = {
                "order_id": str(order.id),
                "quote_version": converted.version,
                "event_id": str(envelope.message_id),
                "audit_event_id": str(audit_id),
            }
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=response_body
            )
            return SalesOrderConversionResult(
                order, converted.version, envelope.message_id, audit_id
            )


def _order_snapshot(order: SalesOrder) -> dict[str, object]:
    return {
        "id": str(order.id),
        "company_id": str(order.company_id),
        "number": order.number,
        "source_quote_id": str(order.source_quote_id),
        "source_quote_revision_number": order.source_quote_revision_number,
        "customer_id": str(order.customer_id),
        "status": order.status,
        "gross_amount": str(order.gross_amount),
        "discount_amount": str(order.discount_amount),
        "net_amount": str(order.net_amount),
        "version": order.version,
        "items": [
            {
                "id": str(item.id),
                "product_id": str(item.product_id),
                "quantity": str(item.quantity),
                "unit_price": str(item.unit_price),
                "discount_amount": str(item.discount_amount),
                "pricing_snapshot_id": str(item.pricing_snapshot_id)
                if item.pricing_snapshot_id
                else None,
            }
            for item in order.items
        ],
    }


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Sales quote cannot be converted.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = ["PostgresSalesOrderConversion"]

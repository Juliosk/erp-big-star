"""Cross-context composition for M6/M11/M12 three-way matching APIs."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.infrastructure import PayableModel, ProvisionalEntryModel
from erp.modules.fiscal.infrastructure import (
    InboundFiscalDocumentItemModel,
    InboundFiscalDocumentModel,
)
from erp.modules.procurement.application import (
    CreateMatchingSession,
    ExecuteMatchingSession,
    ExecuteThreeWayMatch,
    MatchingAuditEntry,
    MatchingExecutionResult,
    MatchingSessionDetail,
    MatchingSessionPage,
    ThreeWayMatchingService,
)
from erp.modules.procurement.domain import (
    FinancialMatchSnapshot,
    MatchingTolerancePolicy,
    PurchaseOrderMatchSnapshot,
    ReceivingFiscalMatchSnapshot,
    ThreeWayMatchLine,
    ThreeWayMatchSession,
    ThreeWayMatchSessionStatus,
    VersionedArtifactReference,
)
from erp.modules.procurement.infrastructure import (
    GoodsReceiptRepository,
    MatchingAuditLogModel,
    PostgresMatchingEventPublisher,
    PurchaseOrderRepository,
    ThreeWayMatchRepository,
)
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService


class PostgresMatchingOperations:
    """Own transaction boundaries across authoritative M6/M11/M12 snapshots."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def create(
        self, command: CreateMatchingSession, *, actor_id: UUID
    ) -> ThreeWayMatchSession:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation="procurement.matching.create",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                return await _replay_session(
                    session,
                    command.company_id,
                    decision,
                )
            try:
                aggregate = await _build_session(session, command, actor_id)
            except ApplicationError:
                raise
            except ValueError as error:
                raise _validation("Invalid three-way matching session.", error) from error
            await ThreeWayMatchRepository(session, company_id=command.company_id).add(
                aggregate, actor_id=actor_id
            )
            await self._idempotency.complete(
                session,
                decision,
                response_status=201,
                response_body={"matching_session_id": str(aggregate.id)},
            )
            return aggregate

    async def execute(
        self, command: ExecuteMatchingSession, *, actor_id: UUID
    ) -> MatchingExecutionResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation="procurement.matching.execute",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                aggregate = await _replay_session(
                    session,
                    command.company_id,
                    decision,
                )
                body = decision.response_body or {}
                return MatchingExecutionResult(
                    aggregate,
                    tuple(UUID(str(value)) for value in body.get("event_ids", [])),
                )
            repository = ThreeWayMatchRepository(session, company_id=command.company_id)
            result = await ThreeWayMatchingService(
                repository,
                PostgresMatchingEventPublisher(session),
            ).execute(
                ExecuteThreeWayMatch(
                    company_id=command.company_id,
                    matching_session_id=command.matching_session_id,
                    expected_version=command.expected_version,
                    actor_id=actor_id,
                    metadata=command.metadata,
                    occurred_at=command.occurred_at,
                )
            )
            await self._idempotency.complete(
                session,
                decision,
                response_status=200,
                response_body={
                    "matching_session_id": str(result.session.id),
                    "event_ids": [str(value) for value in result.event_ids],
                },
            )
            return result

    async def get_detail(
        self, company_id: UUID, matching_session_id: UUID
    ) -> MatchingSessionDetail | None:
        async with self._database.session() as session:
            aggregate = await ThreeWayMatchRepository(session, company_id=company_id).get(
                matching_session_id
            )
            if aggregate is None:
                return None
            values = await session.scalars(
                select(MatchingAuditLogModel)
                .where(
                    MatchingAuditLogModel.company_id == company_id,
                    MatchingAuditLogModel.matching_session_id == matching_session_id,
                )
                .order_by(MatchingAuditLogModel.aggregate_version)
            )
            return MatchingSessionDetail(
                aggregate,
                tuple(
                    MatchingAuditEntry(
                        id=value.id,
                        from_status=ThreeWayMatchSessionStatus(value.from_status)
                        if value.from_status is not None
                        else None,
                        to_status=ThreeWayMatchSessionStatus(value.to_status),
                        aggregate_version=value.aggregate_version,
                        actor_id=value.actor_id,
                        occurred_at=value.occurred_at,
                        details=dict(value.details),
                    )
                    for value in values
                ),
            )

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: ThreeWayMatchSessionStatus | None,
        purchase_order_id: UUID | None,
    ) -> MatchingSessionPage:
        async with self._database.session() as session:
            repository = ThreeWayMatchRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            values = await repository.list(
                status=status,
                purchase_order_id=purchase_order_id,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                purchase_order_id=purchase_order_id,
                limit=1,
                offset=offset + page_size,
            )
            return MatchingSessionPage(values, page, page_size, bool(more))


async def _build_session(
    session: AsyncSession,
    command: CreateMatchingSession,
    actor_id: UUID,
) -> ThreeWayMatchSession:
    _unique_references(command)
    order = await PurchaseOrderRepository(session, company_id=command.company_id).get(
        command.purchase_order_id
    )
    if order is None:
        raise _not_found("Purchase order")

    receipt_repository = GoodsReceiptRepository(session, company_id=command.company_id)
    receipts = []
    for receipt_id in command.goods_receipt_ids:
        receipt = await receipt_repository.get(receipt_id)
        if receipt is None:
            raise _not_found("Goods receipt")
        if receipt.purchase_order_id != order.id or receipt.supplier_id != order.supplier_id:
            raise _validation(
                "Invalid three-way matching session.",
                ValueError("Every goods receipt must belong to the selected purchase order."),
            )
        receipts.append(receipt)

    fiscal_roots = tuple(
        await session.scalars(
            select(InboundFiscalDocumentModel).where(
                InboundFiscalDocumentModel.company_id == command.company_id,
                InboundFiscalDocumentModel.id.in_(command.inbound_fiscal_document_ids),
            )
        )
    )
    if len(fiscal_roots) != len(command.inbound_fiscal_document_ids):
        raise _not_found("Inbound fiscal document")
    fiscal_by_id = {value.id: value for value in fiscal_roots}

    provisional = await session.scalar(
        select(ProvisionalEntryModel).where(
            ProvisionalEntryModel.company_id == command.company_id,
            ProvisionalEntryModel.id == command.provisional_entry_id,
        )
    )
    if provisional is None:
        raise _not_found("Provisional financial entry")
    if provisional.status == "VOIDED":
        raise _validation(
            "Invalid three-way matching session.",
            ValueError("A voided provisional entry cannot participate in matching."),
        )

    payable_id = command.payable_id or provisional.payable_id
    if (
        command.payable_id is not None
        and provisional.payable_id is not None
        and command.payable_id != provisional.payable_id
    ):
        raise _validation(
            "Invalid three-way matching session.",
            ValueError("The payable does not belong to the selected provisional entry."),
        )
    payable = None
    if payable_id is not None:
        payable = await session.scalar(
            select(PayableModel).where(
                PayableModel.company_id == command.company_id,
                PayableModel.id == payable_id,
            )
        )
        if payable is None:
            raise _not_found("Payable")
        if payable.provisional_entry_id != provisional.id:
            raise _validation(
                "Invalid three-way matching session.",
                ValueError("The payable does not belong to the selected provisional entry."),
            )

    order_items = {value.id: value for value in order.items}
    receipt_items = {value.id: value for receipt in receipts for value in receipt.items}
    fiscal_item_ids = tuple(value.fiscal_document_item_id for value in command.lines)
    fiscal_items = tuple(
        await session.scalars(
            select(InboundFiscalDocumentItemModel).where(
                InboundFiscalDocumentItemModel.company_id == command.company_id,
                InboundFiscalDocumentItemModel.id.in_(fiscal_item_ids),
                InboundFiscalDocumentItemModel.inbound_fiscal_document_id.in_(
                    command.inbound_fiscal_document_ids
                ),
            )
        )
    )
    fiscal_items_by_id = {value.id: value for value in fiscal_items}
    if len(fiscal_items_by_id) != len(fiscal_item_ids):
        raise _not_found("Inbound fiscal document item")

    lines = []
    for reference in command.lines:
        purchase_item = order_items.get(reference.purchase_order_item_id)
        receipt_item = receipt_items.get(reference.goods_receipt_item_id)
        fiscal_item = fiscal_items_by_id.get(reference.fiscal_document_item_id)
        if purchase_item is None or receipt_item is None or fiscal_item is None:
            raise _not_found("Matching source item")
        if receipt_item.purchase_order_item_id != purchase_item.id:
            raise _validation(
                "Invalid three-way matching session.",
                ValueError("Receipt and purchase order items must reference the same line."),
            )
        lines.append(
            ThreeWayMatchLine.create(
                company_id=command.company_id,
                match_key=reference.match_key,
                purchase_order_item_id=purchase_item.id,
                goods_receipt_item_id=receipt_item.id,
                fiscal_document_item_id=fiscal_item.id,
                ordered_quantity=purchase_item.quantity,
                received_quantity=receipt_item.received_quantity,
                invoiced_quantity=fiscal_item.quantity,
                ordered_unit_price=purchase_item.unit_price,
                invoiced_unit_price=fiscal_item.unit_price,
                currency=order.currency,
            )
        )

    captured_at = datetime.now(UTC)
    obligation_amount = (
        payable.nominal_amount
        + payable.interest_amount
        + payable.surcharge_amount
        - payable.discount_amount
        if payable is not None
        else provisional.amount
    )
    return ThreeWayMatchSession.create(
        company_id=command.company_id,
        purchase_order_snapshot=PurchaseOrderMatchSnapshot.capture(
            company_id=command.company_id,
            purchase_order_id=order.id,
            purchase_order_version=order.version,
            supplier_id=order.supplier_id,
            currency=order.currency,
            total_amount=order.total_amount,
            captured_at=captured_at,
        ),
        receiving_fiscal_snapshot=ReceivingFiscalMatchSnapshot.capture(
            company_id=command.company_id,
            goods_receipts=tuple(
                VersionedArtifactReference(value.id, value.version) for value in receipts
            ),
            fiscal_documents=tuple(
                VersionedArtifactReference(value, fiscal_by_id[value].version)
                for value in command.inbound_fiscal_document_ids
            ),
            supplier_id=order.supplier_id,
            currency=order.currency,
            invoiced_total_amount=sum(
                (value.total_amount for value in fiscal_roots), Decimal("0.00")
            ),
            captured_at=captured_at,
        ),
        financial_snapshot=FinancialMatchSnapshot.capture(
            company_id=command.company_id,
            provisional_entry_id=provisional.id,
            provisional_entry_version=provisional.version,
            payable_id=payable.id if payable is not None else None,
            payable_version=payable.version if payable is not None else None,
            supplier_id=provisional.supplier_id,
            currency=provisional.currency,
            obligation_amount=obligation_amount,
            captured_at=captured_at,
        ),
        tolerance_policy=MatchingTolerancePolicy.create(
            company_id=command.company_id,
            unit_price_variance_percentage=command.unit_price_variance_percentage,
            quantity_variance_percentage=command.quantity_variance_percentage,
            rounding_absolute_limit=command.rounding_absolute_limit,
            version=command.tolerance_policy_version,
        ),
        lines=tuple(lines),
        created_by=actor_id,
        created_at=captured_at,
    )


def _unique_references(command: CreateMatchingSession) -> None:
    collections = (
        (command.goods_receipt_ids, "goods_receipt_ids"),
        (command.inbound_fiscal_document_ids, "inbound_fiscal_document_ids"),
        (
            tuple(value.purchase_order_item_id for value in command.lines),
            "purchase_order_item_id",
        ),
        (
            tuple(value.goods_receipt_item_id for value in command.lines),
            "goods_receipt_item_id",
        ),
        (
            tuple(value.fiscal_document_item_id for value in command.lines),
            "fiscal_document_item_id",
        ),
    )
    for values, field in collections:
        if not values or len(set(values)) != len(values):
            raise ValueError(f"{field} must be non-empty and unique.")


async def _replay_session(
    session: AsyncSession,
    company_id: UUID,
    decision: IdempotencyDecision,
) -> ThreeWayMatchSession:
    body = decision.response_body or {}
    identity = body.get("matching_session_id")
    if identity is None:
        raise RuntimeError("Stored matching replay has no session identity.")
    aggregate = await ThreeWayMatchRepository(session, company_id=company_id).get(
        UUID(str(identity))
    )
    if aggregate is None:
        raise RuntimeError("Stored matching replay references a missing session.")
    return aggregate


def _scope(company_id: UUID, actor_id: UUID) -> str:
    return f"procurement-matching:{company_id}:{actor_id}"


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


def _validation(message: str, error: Exception) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message=message,
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = ["PostgresMatchingOperations"]

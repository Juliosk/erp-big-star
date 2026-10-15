"""Tenant-bound persistence adapter for M6 three-way matching sessions."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.domain import (
    FinancialMatchSnapshot,
    InvalidMatchingSessionError,
    LineMatchResult,
    MatchingScopeError,
    MatchingSessionConflictError,
    MatchingTolerancePolicy,
    MatchingVersionConflictError,
    MatchStatus,
    PurchaseOrderMatchSnapshot,
    ReceivingFiscalMatchSnapshot,
    ThreeWayMatchLine,
    ThreeWayMatchReport,
    ThreeWayMatchSession,
    ThreeWayMatchSessionStatus,
    VersionedArtifactReference,
)
from erp.modules.procurement.infrastructure.matching_model import (
    MatchingAuditLogModel,
    MatchingSessionItemModel,
    MatchingSessionModel,
)


class ThreeWayMatchRepository:
    """Persist immutable match inputs and versioned lifecycle state."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, aggregate: ThreeWayMatchSession, *, actor_id: UUID) -> None:
        self._write_scope(aggregate, actor_id)
        if aggregate.version != 1 or aggregate.status is not ThreeWayMatchSessionStatus.PENDING:
            raise ValueError("A new matching session must start pending at version one.")
        self._session.add(_root_model(aggregate, actor_id))
        await self._flush()
        self._session.add_all(_item_models(aggregate))
        await self._flush()
        self._session.add(
            _audit_model(
                aggregate,
                actor_id=actor_id,
                from_status=None,
                occurred_at=aggregate.created_at,
            )
        )
        await self._flush()

    async def get(self, matching_session_id: UUID) -> ThreeWayMatchSession | None:
        root = await self._session.scalar(
            select(MatchingSessionModel)
            .where(
                MatchingSessionModel.company_id == self._company_id,
                MatchingSessionModel.id == matching_session_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _aggregate(root, await self._items(root.id))

    async def list(
        self,
        *,
        status: ThreeWayMatchSessionStatus | None = None,
        purchase_order_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[ThreeWayMatchSession, ...]:
        _page(limit, offset)
        statement = select(MatchingSessionModel).where(
            MatchingSessionModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, ThreeWayMatchSessionStatus):
                raise ValueError("status must be an official matching session status.")
            statement = statement.where(MatchingSessionModel.status == status.value)
        if purchase_order_id is not None:
            if not isinstance(purchase_order_id, UUID):
                raise ValueError("purchase_order_id must be a UUID.")
            statement = statement.where(MatchingSessionModel.purchase_order_id == purchase_order_id)
        roots = await self._session.scalars(
            statement.order_by(MatchingSessionModel.created_at, MatchingSessionModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        values = []
        for root in roots:
            values.append(_aggregate(root, await self._items(root.id)))
        return tuple(values)

    async def save(
        self,
        aggregate: ThreeWayMatchSession,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> ThreeWayMatchSession:
        self._write_scope(aggregate, actor_id)
        compare = aggregate.version - 1 if expected_version is None else expected_version
        if compare < 1 or aggregate.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self.get(aggregate.id)
        if current is None or current.version != compare:
            raise MatchingVersionConflictError(
                f"Matching session expected version {compare} is stale."
            )
        _validate_frozen_state(current, aggregate)
        _validate_transition(current.status, aggregate.status)
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(MatchingSessionModel)
                .where(
                    MatchingSessionModel.company_id == self._company_id,
                    MatchingSessionModel.id == aggregate.id,
                    MatchingSessionModel.version == compare,
                )
                .values(**_lifecycle_values(aggregate, actor_id))
            ),
        )
        if updated.rowcount != 1:
            raise MatchingVersionConflictError(
                f"Matching session expected version {compare} is stale."
            )
        await self._persist_results(aggregate)
        self._session.add(
            _audit_model(
                aggregate,
                actor_id=actor_id,
                from_status=current.status,
                occurred_at=_transition_occurred_at(aggregate),
            )
        )
        await self._flush()
        return aggregate

    async def _items(self, matching_session_id: UUID) -> tuple[MatchingSessionItemModel, ...]:
        values = await self._session.scalars(
            select(MatchingSessionItemModel)
            .where(
                MatchingSessionItemModel.company_id == self._company_id,
                MatchingSessionItemModel.matching_session_id == matching_session_id,
            )
            .order_by(MatchingSessionItemModel.line_number)
            .execution_options(populate_existing=True)
        )
        return tuple(values)

    async def _persist_results(self, aggregate: ThreeWayMatchSession) -> None:
        results = (
            {result.line.match_key: result for result in aggregate.report.lines}
            if aggregate.report is not None
            else {}
        )
        for line in aggregate.lines:
            result = results.get(line.match_key)
            await self._session.execute(
                update(MatchingSessionItemModel)
                .where(
                    MatchingSessionItemModel.company_id == self._company_id,
                    MatchingSessionItemModel.matching_session_id == aggregate.id,
                    MatchingSessionItemModel.match_key == line.match_key,
                )
                .values(**_result_values(result))
            )

    def _write_scope(self, aggregate: ThreeWayMatchSession, actor_id: UUID) -> None:
        if not isinstance(aggregate, ThreeWayMatchSession):
            raise TypeError("aggregate must be a ThreeWayMatchSession.")
        if aggregate.company_id != self._company_id:
            raise MatchingScopeError("Matching session is outside the selected company.")
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise MatchingSessionConflictError(
                    "Matching session identity or version already exists for this company."
                ) from error
            raise


def _root_model(aggregate: ThreeWayMatchSession, actor_id: UUID) -> MatchingSessionModel:
    purchase = aggregate.purchase_order_snapshot
    receiving = aggregate.receiving_fiscal_snapshot
    financial = aggregate.financial_snapshot
    policy = aggregate.tolerance_policy
    return MatchingSessionModel(
        id=aggregate.id,
        company_id=aggregate.company_id,
        supplier_id=purchase.supplier_id,
        currency=purchase.currency,
        purchase_order_id=purchase.purchase_order.id,
        purchase_order_version=purchase.purchase_order.version,
        purchase_order_total_amount=purchase.total_amount,
        purchase_order_captured_at=purchase.captured_at,
        goods_receipts_snapshot=_references_json(receiving.goods_receipts),
        fiscal_documents_snapshot=_references_json(receiving.fiscal_documents),
        invoiced_total_amount=receiving.invoiced_total_amount,
        receiving_fiscal_captured_at=receiving.captured_at,
        provisional_entry_id=financial.provisional_entry.id,
        provisional_entry_version=financial.provisional_entry.version,
        payable_id=financial.payable.id if financial.payable is not None else None,
        payable_version=financial.payable.version if financial.payable is not None else None,
        obligation_amount=financial.obligation_amount,
        financial_captured_at=financial.captured_at,
        unit_price_variance_percentage=policy.unit_price_variance_percentage,
        quantity_variance_percentage=policy.quantity_variance_percentage,
        rounding_absolute_limit=policy.rounding_absolute_limit,
        tolerance_policy_version=policy.version,
        created_at=aggregate.created_at,
        created_by=aggregate.created_by,
        **_lifecycle_values(aggregate, actor_id),
    )


def _lifecycle_values(aggregate: ThreeWayMatchSession, actor_id: UUID) -> dict[str, Any]:
    return {
        "status": aggregate.status.value,
        "report_status": aggregate.report.status.value if aggregate.report is not None else None,
        "started_at": aggregate.started_at,
        "completed_at": aggregate.completed_at,
        "decision_by": aggregate.decision_by,
        "decision_workflow_instance_id": aggregate.decision_workflow_instance_id,
        "decision_reason": aggregate.decision_reason,
        "decided_at": aggregate.decided_at,
        "version": aggregate.version,
        "updated_at": datetime.now(UTC),
        "updated_by": actor_id,
    }


def _item_models(aggregate: ThreeWayMatchSession) -> list[MatchingSessionItemModel]:
    results = (
        {result.line.match_key: result for result in aggregate.report.lines}
        if aggregate.report is not None
        else {}
    )
    return [
        MatchingSessionItemModel(
            company_id=aggregate.company_id,
            matching_session_id=aggregate.id,
            line_number=line_number,
            match_key=line.match_key,
            purchase_order_item_id=line.purchase_order_item_id,
            goods_receipt_item_id=line.goods_receipt_item_id,
            fiscal_document_item_id=line.fiscal_document_item_id,
            ordered_quantity=line.ordered_quantity,
            received_quantity=line.received_quantity,
            invoiced_quantity=line.invoiced_quantity,
            ordered_unit_price=line.ordered_unit_price,
            invoiced_unit_price=line.invoiced_unit_price,
            currency=line.currency,
            **_result_values(results.get(line.match_key)),
        )
        for line_number, line in enumerate(aggregate.lines, start=1)
    ]


def _result_values(result: LineMatchResult | None) -> dict[str, Any]:
    return {
        "result_status": result.status.value if result is not None else None,
        "quantity_delta": result.quantity_delta if result is not None else None,
        "unit_price_delta": result.unit_price_delta if result is not None else None,
        "allowed_quantity_delta": result.allowed_quantity_delta if result is not None else None,
        "allowed_unit_price_delta": result.allowed_unit_price_delta if result is not None else None,
        "reasons": list(result.reasons) if result is not None else None,
    }


def _audit_model(
    aggregate: ThreeWayMatchSession,
    *,
    actor_id: UUID,
    from_status: ThreeWayMatchSessionStatus | None,
    occurred_at: datetime,
) -> MatchingAuditLogModel:
    return MatchingAuditLogModel(
        id=uuid4(),
        company_id=aggregate.company_id,
        matching_session_id=aggregate.id,
        from_status=from_status.value if from_status is not None else None,
        to_status=aggregate.status.value,
        aggregate_version=aggregate.version,
        actor_id=actor_id,
        occurred_at=occurred_at,
        details={
            "report_status": aggregate.report.status.value
            if aggregate.report is not None
            else None,
            "decision_workflow_instance_id": str(aggregate.decision_workflow_instance_id)
            if aggregate.decision_workflow_instance_id is not None
            else None,
        },
    )


def _aggregate(
    root: MatchingSessionModel,
    items: tuple[MatchingSessionItemModel, ...],
) -> ThreeWayMatchSession:
    policy = MatchingTolerancePolicy.create(
        company_id=root.company_id,
        unit_price_variance_percentage=root.unit_price_variance_percentage,
        quantity_variance_percentage=root.quantity_variance_percentage,
        rounding_absolute_limit=root.rounding_absolute_limit,
        version=root.tolerance_policy_version,
    )
    lines = tuple(_line(item) for item in items)
    report = (
        ThreeWayMatchReport(
            company_id=root.company_id,
            policy=policy,
            lines=tuple(_line_result(item, line) for item, line in zip(items, lines, strict=True)),
            status=MatchStatus(root.report_status),
        )
        if root.report_status is not None
        else None
    )
    return ThreeWayMatchSession(
        id=root.id,
        company_id=root.company_id,
        purchase_order_snapshot=PurchaseOrderMatchSnapshot.capture(
            company_id=root.company_id,
            purchase_order_id=root.purchase_order_id,
            purchase_order_version=root.purchase_order_version,
            supplier_id=root.supplier_id,
            currency=root.currency,
            total_amount=root.purchase_order_total_amount,
            captured_at=root.purchase_order_captured_at,
        ),
        receiving_fiscal_snapshot=ReceivingFiscalMatchSnapshot.capture(
            company_id=root.company_id,
            goods_receipts=_references(root.goods_receipts_snapshot),
            fiscal_documents=_references(root.fiscal_documents_snapshot),
            supplier_id=root.supplier_id,
            currency=root.currency,
            invoiced_total_amount=root.invoiced_total_amount,
            captured_at=root.receiving_fiscal_captured_at,
        ),
        financial_snapshot=FinancialMatchSnapshot.capture(
            company_id=root.company_id,
            provisional_entry_id=root.provisional_entry_id,
            provisional_entry_version=root.provisional_entry_version,
            payable_id=root.payable_id,
            payable_version=root.payable_version,
            supplier_id=root.supplier_id,
            currency=root.currency,
            obligation_amount=root.obligation_amount,
            captured_at=root.financial_captured_at,
        ),
        tolerance_policy=policy,
        lines=lines,
        status=ThreeWayMatchSessionStatus(root.status),
        created_by=root.created_by,
        created_at=root.created_at,
        started_at=root.started_at,
        completed_at=root.completed_at,
        report=report,
        decision_by=root.decision_by,
        decision_workflow_instance_id=root.decision_workflow_instance_id,
        decision_reason=root.decision_reason,
        decided_at=root.decided_at,
        version=root.version,
    )


def _line(model: MatchingSessionItemModel) -> ThreeWayMatchLine:
    return ThreeWayMatchLine.create(
        company_id=model.company_id,
        match_key=model.match_key,
        purchase_order_item_id=model.purchase_order_item_id,
        goods_receipt_item_id=model.goods_receipt_item_id,
        fiscal_document_item_id=model.fiscal_document_item_id,
        ordered_quantity=model.ordered_quantity,
        received_quantity=model.received_quantity,
        invoiced_quantity=model.invoiced_quantity,
        ordered_unit_price=model.ordered_unit_price,
        invoiced_unit_price=model.invoiced_unit_price,
        currency=model.currency,
    )


def _line_result(model: MatchingSessionItemModel, line: ThreeWayMatchLine) -> LineMatchResult:
    values = (
        model.result_status,
        model.quantity_delta,
        model.unit_price_delta,
        model.allowed_quantity_delta,
        model.allowed_unit_price_delta,
        model.reasons,
    )
    if any(value is None for value in values):
        raise InvalidMatchingSessionError("Persisted report contains an incomplete line result.")
    return LineMatchResult(
        line=line,
        status=MatchStatus(cast(str, model.result_status)),
        quantity_delta=cast(Decimal, model.quantity_delta),
        unit_price_delta=cast(Decimal, model.unit_price_delta),
        allowed_quantity_delta=cast(Decimal, model.allowed_quantity_delta),
        allowed_unit_price_delta=cast(Decimal, model.allowed_unit_price_delta),
        reasons=tuple(cast(list[str], model.reasons)),
    )


def _references_json(
    references: tuple[VersionedArtifactReference, ...],
) -> list[dict[str, object]]:
    return [{"id": str(reference.id), "version": reference.version} for reference in references]


def _references(values: list[dict[str, Any]]) -> tuple[VersionedArtifactReference, ...]:
    try:
        return tuple(
            VersionedArtifactReference(id=UUID(str(value["id"])), version=int(value["version"]))
            for value in values
        )
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidMatchingSessionError("Persisted artifact references are invalid.") from error


def _validate_frozen_state(
    current: ThreeWayMatchSession,
    candidate: ThreeWayMatchSession,
) -> None:
    if (
        current.purchase_order_snapshot != candidate.purchase_order_snapshot
        or current.receiving_fiscal_snapshot != candidate.receiving_fiscal_snapshot
        or current.financial_snapshot != candidate.financial_snapshot
        or current.tolerance_policy != candidate.tolerance_policy
        or current.lines != candidate.lines
        or current.created_by != candidate.created_by
        or current.created_at != candidate.created_at
    ):
        raise InvalidMatchingSessionError("Matching source snapshots are immutable after creation.")


def _validate_transition(
    current: ThreeWayMatchSessionStatus,
    candidate: ThreeWayMatchSessionStatus,
) -> None:
    allowed = {
        ThreeWayMatchSessionStatus.PENDING: {ThreeWayMatchSessionStatus.RUNNING},
        ThreeWayMatchSessionStatus.RUNNING: {
            ThreeWayMatchSessionStatus.MATCHED,
            ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED,
        },
        ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED: {
            ThreeWayMatchSessionStatus.OVERRIDDEN,
            ThreeWayMatchSessionStatus.REJECTED,
        },
    }
    if candidate not in allowed.get(current, set()):
        raise InvalidMatchingSessionError(
            f"Persistence transition {current.value} -> {candidate.value} is not allowed."
        )


def _transition_occurred_at(aggregate: ThreeWayMatchSession) -> datetime:
    return (
        aggregate.decided_at or aggregate.completed_at or aggregate.started_at or datetime.now(UTC)
    )


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["ThreeWayMatchRepository"]

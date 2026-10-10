"""Tenant-bound repository for physical-fiscal reconciliation reports."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.fiscal.application.reconciliation import (
    FiscalReceivingReconciliation,
    ReconciliationIssue,
    ReconciliationIssueKind,
    ReconciliationStatus,
)
from erp.modules.fiscal.infrastructure.reconciliation_model import (
    FiscalReceivingReconciliationModel,
)
from erp.platform.errors import ApplicationError


class FiscalReceivingReconciliationRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, reconciliation: FiscalReceivingReconciliation, *, actor_id: UUID) -> None:
        if reconciliation.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The reconciliation is outside the selected company.",
                status_code=403,
            )
        self._session.add(
            FiscalReceivingReconciliationModel(
                id=reconciliation.id,
                company_id=reconciliation.company_id,
                inbound_fiscal_document_id=reconciliation.inbound_fiscal_document_id,
                goods_receipt_id=reconciliation.goods_receipt_id,
                purchase_order_id=reconciliation.purchase_order_id,
                status=reconciliation.status.value,
                report=[_issue_payload(value) for value in reconciliation.issues],
                financial_blocked=reconciliation.financial_blocked,
                physical_pending=reconciliation.physical_pending,
                inventory_transaction_ids=[
                    str(value) for value in reconciliation.inventory_transaction_ids
                ],
                reconciled_at=reconciliation.reconciled_at,
                version=reconciliation.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="RECONCILIATION_ALREADY_EXISTS",
                    message="The inbound document or receipt was already reconciled.",
                    status_code=409,
                ) from error
            raise

    async def get_by_inbound(
        self, inbound_document_id: UUID
    ) -> FiscalReceivingReconciliation | None:
        model = await self._session.scalar(
            select(FiscalReceivingReconciliationModel).where(
                FiscalReceivingReconciliationModel.company_id == self._company_id,
                FiscalReceivingReconciliationModel.inbound_fiscal_document_id
                == inbound_document_id,
            )
        )
        return None if model is None else _domain(model)


def _issue_payload(value: ReconciliationIssue) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "message": value.message,
        "inbound_line_number": value.inbound_line_number,
        "receipt_item_id": None if value.receipt_item_id is None else str(value.receipt_item_id),
        "expected": value.expected,
        "actual": value.actual,
    }


def _domain(model: FiscalReceivingReconciliationModel) -> FiscalReceivingReconciliation:
    return FiscalReceivingReconciliation(
        id=model.id,
        company_id=model.company_id,
        inbound_fiscal_document_id=model.inbound_fiscal_document_id,
        goods_receipt_id=model.goods_receipt_id,
        purchase_order_id=model.purchase_order_id,
        status=ReconciliationStatus(model.status),
        issues=tuple(
            ReconciliationIssue(
                kind=ReconciliationIssueKind(str(value["kind"])),
                message=str(value["message"]),
                inbound_line_number=value.get("inbound_line_number"),
                receipt_item_id=(
                    None
                    if value.get("receipt_item_id") is None
                    else UUID(str(value["receipt_item_id"]))
                ),
                expected=value.get("expected"),
                actual=value.get("actual"),
            )
            for value in model.report
        ),
        financial_blocked=model.financial_blocked,
        physical_pending=model.physical_pending,
        inventory_transaction_ids=tuple(UUID(value) for value in model.inventory_transaction_ids),
        version=model.version,
        reconciled_at=model.reconciled_at,
    )


__all__ = ["FiscalReceivingReconciliationRepository"]

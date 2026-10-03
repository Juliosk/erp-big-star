"""Pure SoD, approval status and atomic effect contract tests."""

import asyncio
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.application import ProcurementCommandMetadata
from erp.modules.procurement.application.purchasing import enforce_separation_of_duties
from erp.modules.procurement.domain import PaymentTerms, PurchaseOrder, PurchaseOrderStatus
from erp.modules.procurement.infrastructure.purchasing_effects import (
    PURCHASE_APPROVAL_REQUESTED,
    record_purchasing_effect,
)
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.errors import ApplicationError
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxService


def _order(*, buyer_id: UUID | None = None) -> PurchaseOrder:
    company_id, requisition_item_id, product_id = uuid4(), uuid4(), uuid4()
    return PurchaseOrder.create_from_requisition(
        company_id=company_id,
        number="PO-APPROVAL-1",
        supplier_id=uuid4(),
        source_requisition_id=uuid4(),
        buyer_id=buyer_id or uuid4(),
        currency_code="BRL",
        payment_terms=PaymentTerms.create(
            code="30D", description="Trinta dias", installment_days=(30,)
        ),
        lines=((requisition_item_id, product_id, "10", "12.34", "BRL"),),
    )


def test_purchase_order_supports_explicit_rejection_only_while_pending() -> None:
    pending = _order().submit_for_approval()
    rejected = pending.reject()
    assert rejected.status is PurchaseOrderStatus.REJECTED
    assert rejected.version == pending.version + 1
    with pytest.raises(ValueError, match="only pending"):
        rejected.reject()


def test_separation_of_duties_rejects_owner_and_accepts_another_actor() -> None:
    owner = uuid4()
    with pytest.raises(ApplicationError) as captured:
        enforce_separation_of_duties(owner_id=owner, approver_id=owner)
    assert captured.value.code == "SOD_VIOLATION"
    enforce_separation_of_duties(owner_id=owner, approver_id=uuid4())


def test_audit_and_outbox_are_staged_on_the_same_caller_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        before = _order()
        after = before.submit_for_approval()
        session = cast(AsyncSession, object())
        calls: list[tuple[str, object]] = []

        async def audit(_self: AuditService, received: AsyncSession, event: AuditEvent) -> UUID:
            calls.append(("audit", received))
            assert event.operation == PURCHASE_APPROVAL_REQUESTED
            return uuid4()

        async def outbox(
            _self: OutboxService, received: AsyncSession, envelope: MessageEnvelope
        ) -> None:
            calls.append(("outbox", received))
            assert envelope.message_type == PURCHASE_APPROVAL_REQUESTED
            payload = envelope.payload
            assert payload["amount"] == str(Decimal("123.40"))
            assert payload["source_type"] == "PURCHASE_ORDER"

        monkeypatch.setattr(AuditService, "record", audit)
        monkeypatch.setattr(OutboxService, "enqueue", outbox)
        metadata = ProcurementCommandMetadata(uuid4(), uuid4(), "127.0.0.1")
        event_id, audit_id = await record_purchasing_effect(
            session,
            before=before,
            after=after,
            event_type=PURCHASE_APPROVAL_REQUESTED,
            actor_id=before.buyer_id,
            metadata=metadata,
        )
        assert isinstance(event_id, UUID)
        assert isinstance(audit_id, UUID)
        assert calls == [("audit", session), ("outbox", session)]

    asyncio.run(scenario())

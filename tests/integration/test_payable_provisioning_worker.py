"""M11/M6 events provision M12 payables atomically through the Inbox."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from erp.modules.finance.domain import (
    Payable,
    PayableSegregationPolicy,
    PayableStatus,
    ProvisionalEntryOrigin,
    ProvisionalEntryStatus,
    ProvisionalFinancialEntry,
)
from erp.modules.finance.infrastructure import (
    FINANCE_PAYABLE_PROVISIONING_CONSUMER,
    FISCAL_DOCUMENT_AUTHORIZED,
    FISCAL_DOCUMENT_CANCELLED,
    PURCHASE_ORDER_APPROVED,
    FiscalEventConsumer,
    PayableModel,
    PayableRepository,
    ProvisionalEntryRepository,
)
from erp.modules.fiscal.application import (
    CancelFiscalDocument,
    FiscalIssuanceWorker,
    FiscalWorkerMetadata,
    SefazEndpoint,
    SefazEnvironment,
    SefazSubmissionMode,
    TransmitFiscalDocument,
)
from erp.modules.fiscal.infrastructure import (
    FiscalDocumentItemModel,
    FiscalDocumentModel,
    FiscalDocumentRepository,
    PostgresFiscalIssuanceStore,
    SefazMockAdapter,
)
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.inbox import InboxEventModel, InboxRepository, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_payable_repository import finance_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key, draft

pytestmark = pytest.mark.integration


@asynccontextmanager
async def provisioning_fixture() -> AsyncIterator[ProcurementFixture]:
    async with finance_fixture() as data:
        try:
            yield data
        finally:
            companies = (data.company_id, data.other_company_id)
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == FINANCE_PAYABLE_PROVISIONING_CONSUMER
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.payload["company_id"]
                        .as_string()
                        .in_(tuple(str(value) for value in companies))
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.company_id.in_(companies))
                )
                await session.execute(
                    delete(FiscalDocumentItemModel).where(
                        FiscalDocumentItemModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(FiscalDocumentModel).where(FiscalDocumentModel.company_id.in_(companies))
                )


def _purchase_event(
    data: ProcurementFixture,
    *,
    supplier_id: UUID,
    supplier_tax_id: str,
    amount: Decimal,
) -> MessageEnvelope:
    order_id = uuid4()
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=PURCHASE_ORDER_APPROVED,
        event_version=1,
        producer_module="procurement",
        producer_domain="procurement",
        aggregate_type="purchase_order",
        aggregate_id=order_id,
        aggregate_version=3,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "company_id": str(data.company_id),
            "source_id": str(order_id),
            "requested_by": str(data.actor_id),
            "supplier_id": str(supplier_id),
            "supplier_tax_id": supplier_tax_id,
            "document_number": f"PO-{uuid4().hex[:10]}",
            "amount": str(amount),
            "currency": "BRL",
            "installment_days": [30, 60],
        },
    )


def _standalone_fiscal_event(data: ProcurementFixture) -> MessageEnvelope:
    document_id = uuid4()
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=FISCAL_DOCUMENT_AUTHORIZED,
        event_version=1,
        producer_module="fiscal",
        producer_domain="fiscal",
        aggregate_type="fiscal_document",
        aggregate_id=document_id,
        aggregate_version=3,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "company_id": str(data.company_id),
            "requested_by": str(data.actor_id),
            "supplier_id": str(uuid4()),
            "supplier_tax_id": "12345678000195",
            "document_number": f"55-1-{uuid4().int % 100000}",
            "total_amount": "100.00",
            "currency": "BRL",
            "installments": [
                {"due_date": "2026-11-10", "amount": "40.00"},
                {"due_date": "2026-12-10", "amount": "60.00"},
            ],
        },
    )


def _cancellation_event(data: ProcurementFixture, document_id: UUID) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=FISCAL_DOCUMENT_CANCELLED,
        event_version=1,
        producer_module="fiscal",
        producer_domain="fiscal",
        aggregate_type="fiscal_document",
        aggregate_id=document_id,
        aggregate_version=4,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={"requested_by": str(data.actor_id)},
    )


async def _outbox_envelope(
    data: ProcurementFixture,
    *,
    aggregate_id: UUID,
    event_type: str,
) -> MessageEnvelope:
    async with data.database.session() as session:
        model = (
            await session.scalars(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_id == aggregate_id,
                    OutboxEventModel.event_type == event_type,
                )
            )
        ).one()
        return MessageEnvelope.model_validate(model.payload)


def test_m11_authorization_and_cancellation_reuse_purchase_provision_exactly_once() -> None:
    async def scenario() -> None:
        async with provisioning_fixture() as data:
            fiscal_draft = replace(
                draft(),
                company_id=data.company_id,
                number=uuid4().int % 1_000_000 + 1,
            )
            issuing = fiscal_draft.start_issuing()
            async with data.database.session() as session, session.begin():
                fiscal_documents = FiscalDocumentRepository(session, company_id=data.company_id)
                await fiscal_documents.add(fiscal_draft, actor_id=data.actor_id)
                await fiscal_documents.save(issuing, actor_id=data.actor_id)

            consumer = FiscalEventConsumer(data.database)
            purchase_event = _purchase_event(
                data,
                supplier_id=uuid4(),
                supplier_tax_id=fiscal_draft.issuer.tax_id,
                amount=fiscal_draft.totals.total_amount,
            )
            purchase_result = await consumer.consume(purchase_event)
            duplicate = await consumer.consume(purchase_event)
            semantic_purchase_replay = await consumer.consume(
                purchase_event.model_copy(update={"message_id": uuid4()})
            )
            assert purchase_result.processed
            assert not purchase_result.duplicate
            assert duplicate.duplicate
            assert not duplicate.processed
            assert semantic_purchase_replay.processed

            worker = FiscalIssuanceWorker(
                PostgresFiscalIssuanceStore(data.database), SefazMockAdapter()
            )
            metadata = FiscalWorkerMetadata(uuid4(), uuid4(), "127.0.0.1")
            authorized = await worker.transmit(
                TransmitFiscalDocument(
                    data.company_id,
                    issuing.id,
                    issuing.version,
                    data.actor_id,
                    access_key(issuing.model.value),
                    b'<NFe><infNFe Id="NFe159"/></NFe>',
                    "#NFe159",
                    str(issuing.number).zfill(15),
                    SefazEndpoint("SP", SefazEnvironment.HOMOLOGATION),
                    SefazSubmissionMode.SYNCHRONOUS,
                    metadata,
                )
            )
            authorization_event = await _outbox_envelope(
                data,
                aggregate_id=authorized.id,
                event_type=FISCAL_DOCUMENT_AUTHORIZED,
            )
            authorization_result = await consumer.consume(authorization_event)
            authorization_duplicate = await consumer.consume(authorization_event)
            semantic_authorization_replay = await consumer.consume(
                authorization_event.model_copy(update={"message_id": uuid4()})
            )
            assert authorization_result.processed
            assert not authorization_result.duplicate
            assert authorization_duplicate.duplicate
            assert semantic_authorization_replay.processed

            async with data.database.session() as session, session.begin():
                entries = ProvisionalEntryRepository(session, company_id=data.company_id)
                purchase_entry = await entries.get_by_source_id(
                    origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
                    source_id=purchase_event.aggregate_id,
                )
                fiscal_entry = await entries.get_by_source_id(
                    origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
                    source_id=authorized.id,
                )
                assert purchase_entry is not None
                assert fiscal_entry is not None
                assert purchase_entry.status is ProvisionalEntryStatus.CONVERTED
                assert fiscal_entry.status is ProvisionalEntryStatus.CONVERTED
                assert fiscal_entry.payable_id == purchase_entry.payable_id
                assert purchase_entry.payable_id is not None
                payables = PayableRepository(session, company_id=data.company_id)
                title = await payables.get(purchase_entry.payable_id)
                assert title is not None
                assert len(title.installments) == 2
                pending = title.submit_for_approval()
                await payables.save(pending, actor_id=data.actor_id)
                approved = pending.approve(
                    approver_id=uuid4(),
                    policy=PayableSegregationPolicy(Decimal("100.00")),
                )
                await payables.save(approved, actor_id=data.actor_id)
                scheduled = approved.schedule((uuid4(), uuid4()))
                await payables.save(scheduled, actor_id=data.actor_id)

            cancelled = await worker.cancel(
                CancelFiscalDocument(
                    data.company_id,
                    authorized.id,
                    authorized.version,
                    data.actor_id,
                    "Cancelamento financeiro antes da liquidacao",
                    SefazEndpoint("SP", SefazEnvironment.HOMOLOGATION),
                    metadata,
                )
            )
            cancellation_event = await _outbox_envelope(
                data,
                aggregate_id=cancelled.id,
                event_type=FISCAL_DOCUMENT_CANCELLED,
            )
            cancellation_result = await consumer.consume(cancellation_event)
            semantic_cancellation_replay = await consumer.consume(
                cancellation_event.model_copy(update={"message_id": uuid4()})
            )
            assert cancellation_result.processed
            assert semantic_cancellation_replay.processed

            async with data.database.session() as session:
                entries = ProvisionalEntryRepository(session, company_id=data.company_id)
                fiscal_entry = await entries.get_by_source_id(
                    origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
                    source_id=authorized.id,
                )
                assert fiscal_entry is not None
                assert fiscal_entry.status is ProvisionalEntryStatus.VOIDED
                assert fiscal_entry.payable_id is not None
                title = await PayableRepository(session, company_id=data.company_id).get(
                    fiscal_entry.payable_id
                )
                assert title is not None
                assert title.status is PayableStatus.REJECTED
                assert all(item.schedule_id is None for item in title.installments)
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEventModel)
                        .where(
                            AuditEventModel.company_id == data.company_id,
                            AuditEventModel.module == "finance",
                        )
                    )
                    == 3
                )
                inbox = await InboxRepository().get(
                    session,
                    consumer_name=FINANCE_PAYABLE_PROVISIONING_CONSUMER,
                    event_id=authorization_event.message_id,
                )
                assert inbox is not None
                assert inbox.status == InboxStatus.PROCESSED
                assert inbox.attempts == 2

    asyncio.run(scenario())


def test_fiscal_provisioning_rolls_back_inbox_and_financial_effect_on_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_audit(*_: object, **__: object) -> UUID:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditService, "record", fail_audit)

    async def scenario() -> None:
        async with provisioning_fixture() as data:
            envelope = _standalone_fiscal_event(data)
            with pytest.raises(RuntimeError, match="audit unavailable"):
                await FiscalEventConsumer(data.database).consume(envelope)
            async with data.database.session() as session:
                entry = await ProvisionalEntryRepository(
                    session, company_id=data.company_id
                ).get_by_source_id(
                    origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
                    source_id=envelope.aggregate_id,
                )
                assert entry is None
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(PayableModel)
                        .where(PayableModel.company_id == data.company_id)
                    )
                    == 0
                )
                assert (
                    await InboxRepository().get(
                        session,
                        consumer_name=FINANCE_PAYABLE_PROVISIONING_CONSUMER,
                        event_id=envelope.message_id,
                    )
                    is None
                )

    asyncio.run(scenario())


def test_consumer_rejects_unsupported_and_cross_tenant_envelopes_before_inbox() -> None:
    async def scenario() -> None:
        async with provisioning_fixture() as data:
            consumer = FiscalEventConsumer(data.database)
            valid = _standalone_fiscal_event(data)
            with pytest.raises(ValueError, match="Unsupported"):
                await consumer.consume(valid.model_copy(update={"event_version": 2}))
            crossed = valid.model_copy(
                update={"payload": {**valid.payload, "company_id": str(data.other_company_id)}}
            )
            with pytest.raises(ValueError, match="company boundary"):
                await consumer.consume(crossed)
            wrong_source = valid.model_copy(
                update={"payload": {**valid.payload, "source_id": str(uuid4())}}
            )
            with pytest.raises(ValueError, match="source identity"):
                await consumer.consume(wrong_source)

            without_supplier = _standalone_fiscal_event(data).model_copy(
                update={
                    "payload": {
                        key: value
                        for key, value in _standalone_fiscal_event(data).payload.items()
                        if key != "supplier_id"
                    }
                }
            )
            with pytest.raises(ValueError, match="supplier_id"):
                await consumer.consume(without_supplier)

            cancellation = valid.model_copy(
                update={
                    "message_id": uuid4(),
                    "message_type": FISCAL_DOCUMENT_CANCELLED,
                    "aggregate_id": uuid4(),
                    "payload": {"requested_by": str(data.actor_id)},
                }
            )
            with pytest.raises(ValueError, match="no associated"):
                await consumer.consume(cancellation)

    asyncio.run(scenario())


def test_provisioning_fails_closed_on_broken_links_and_compensates_terminal_variants() -> None:
    async def scenario() -> None:
        async with provisioning_fixture() as data:
            consumer = FiscalEventConsumer(data.database)
            supplier_id = uuid4()
            async with data.database.session() as session, session.begin():
                entries = ProvisionalEntryRepository(session, company_id=data.company_id)
                purchase_source = uuid4()
                purchase = ProvisionalFinancialEntry.create(
                    company_id=data.company_id,
                    origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
                    source_id=purchase_source,
                    source_version=3,
                    supplier_id=supplier_id,
                    supplier_tax_id="12345678000195",
                    amount=Decimal("100.00"),
                    created_by=data.actor_id,
                )
                await entries.add(purchase, actor_id=data.actor_id)
                await entries.save(
                    purchase.convert(uuid4()),
                    actor_id=data.actor_id,
                )

            fiscal_without_supplier = _standalone_fiscal_event(data)
            fiscal_without_supplier = fiscal_without_supplier.model_copy(
                update={
                    "payload": {
                        key: value
                        for key, value in fiscal_without_supplier.payload.items()
                        if key != "supplier_id"
                    }
                }
            )
            with pytest.raises(ValueError, match="missing payable"):
                await consumer.consume(fiscal_without_supplier)

            missing_payable_source = uuid4()
            open_source = uuid4()
            rejected_source = uuid4()
            async with data.database.session() as session, session.begin():
                entries = ProvisionalEntryRepository(session, company_id=data.company_id)
                missing = ProvisionalFinancialEntry.create(
                    company_id=data.company_id,
                    origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
                    source_id=missing_payable_source,
                    source_version=3,
                    supplier_id=supplier_id,
                    supplier_tax_id="12345678000195",
                    amount=Decimal("101.00"),
                    created_by=data.actor_id,
                )
                await entries.add(missing, actor_id=data.actor_id)
                await entries.save(missing.convert(uuid4()), actor_id=data.actor_id)
                opened = replace(
                    missing, id=uuid4(), source_id=open_source, amount=Decimal("102.00")
                )
                await entries.add(opened, actor_id=data.actor_id)

                rejected_entry = replace(
                    missing,
                    id=uuid4(),
                    source_id=rejected_source,
                    amount=Decimal("103.00"),
                )
                title = Payable.create(
                    company_id=data.company_id,
                    number=f"NFE-{uuid4().hex[:10]}",
                    supplier_id=supplier_id,
                    supplier_tax_id=rejected_entry.supplier_tax_id,
                    created_by=data.actor_id,
                    provisional_entry_id=rejected_entry.id,
                    nominal_amount=rejected_entry.amount,
                    installment_plan=((date(2026, 11, 10), rejected_entry.amount),),
                )
                await entries.add(rejected_entry, actor_id=data.actor_id)
                payables = PayableRepository(session, company_id=data.company_id)
                await payables.add(title, actor_id=data.actor_id)
                await entries.save(rejected_entry.convert(title.id), actor_id=data.actor_id)
                await payables.save(
                    title.cancel_from_source(
                        cancelled_by=data.actor_id,
                        reason="Fiscal source invalidated.",
                    ),
                    actor_id=data.actor_id,
                )

            with pytest.raises(ValueError, match="missing payable"):
                await consumer.consume(_cancellation_event(data, missing_payable_source))
            assert (await consumer.consume(_cancellation_event(data, open_source))).processed
            assert (await consumer.consume(_cancellation_event(data, rejected_source))).processed

    asyncio.run(scenario())

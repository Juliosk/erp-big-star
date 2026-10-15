"""Three-way matching persistence integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect, select, text

from erp.modules.finance.infrastructure import ProvisionalEntryModel
from erp.modules.fiscal.infrastructure import (
    InboundFiscalDocumentItemModel,
    InboundFiscalDocumentModel,
)
from erp.modules.procurement.domain import (
    FinancialMatchSnapshot,
    InvalidMatchingSessionError,
    MatchingScopeError,
    MatchingSessionConflictError,
    MatchingTolerancePolicy,
    MatchingVersionConflictError,
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
    MatchingSessionItemModel,
    MatchingSessionModel,
    PurchaseOrderRepository,
    ThreeWayMatchRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_procurement_goods_receipt_repository import goods_receipt_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class MatchingFixture:
    data: ProcurementFixture
    aggregate: ThreeWayMatchSession


@asynccontextmanager
async def matching_fixture() -> AsyncIterator[MatchingFixture]:
    async with goods_receipt_fixture() as (data, receipt):
        inbound_id = uuid4()
        inbound_item_id = uuid4()
        provisional_entry_id = uuid4()
        captured_at = datetime.now(UTC)
        async with data.database.session() as session, session.begin():
            await GoodsReceiptRepository(session, company_id=data.company_id).add(
                receipt, actor_id=data.actor_id
            )
            purchase_order = await PurchaseOrderRepository(session, company_id=data.company_id).get(
                receipt.purchase_order_id
            )
            assert purchase_order is not None
            order_item = purchase_order.items[0]
            receipt_item = receipt.items[0]
            session.add(
                InboundFiscalDocumentModel(
                    id=inbound_id,
                    company_id=data.company_id,
                    access_key=str(uuid4().int % (10**44)).zfill(44),
                    model="55",
                    series=1,
                    number=uuid4().int % 1_000_000 + 1,
                    issued_at=captured_at,
                    authorization_protocol=str(uuid4().int)[:15],
                    supplier_tax_id="12345678000195",
                    supplier_snapshot={"supplier_id": str(receipt.supplier_id)},
                    recipient_snapshot={"company_id": str(data.company_id)},
                    products_amount=purchase_order.total_amount,
                    total_amount=purchase_order.total_amount,
                    source_xml="<nfeProc />",
                    mde_status="CONFIRMED",
                    version=1,
                    created_by=data.actor_id,
                    updated_by=data.actor_id,
                )
            )
            await session.flush()
            session.add(
                InboundFiscalDocumentItemModel(
                    id=inbound_item_id,
                    company_id=data.company_id,
                    inbound_fiscal_document_id=inbound_id,
                    line_number=1,
                    supplier_code="MATCH-ITEM",
                    description="Matching fixture item",
                    ncm="95030099",
                    cfop="1102",
                    unit_of_measure="UN",
                    quantity=receipt_item.received_quantity,
                    unit_price=order_item.unit_price,
                    total_amount=purchase_order.total_amount,
                    created_by=data.actor_id,
                )
            )
            session.add(
                ProvisionalEntryModel(
                    id=provisional_entry_id,
                    company_id=data.company_id,
                    origin="AUTHORIZED_FISCAL_DOCUMENT",
                    source_id=inbound_id,
                    source_version=1,
                    supplier_id=receipt.supplier_id,
                    supplier_tax_id="12345678000195",
                    amount=purchase_order.total_amount,
                    currency=purchase_order.currency,
                    status="OPEN",
                    payable_id=None,
                    void_reason=None,
                    version=1,
                    created_by=data.actor_id,
                    updated_by=data.actor_id,
                )
            )

        line = ThreeWayMatchLine.create(
            company_id=data.company_id,
            match_key="LINE-001",
            purchase_order_item_id=order_item.id,
            goods_receipt_item_id=receipt_item.id,
            fiscal_document_item_id=inbound_item_id,
            ordered_quantity=order_item.quantity,
            received_quantity=receipt_item.received_quantity,
            invoiced_quantity=receipt_item.received_quantity,
            ordered_unit_price=order_item.unit_price,
            invoiced_unit_price=order_item.unit_price,
            currency=purchase_order.currency,
        )
        aggregate = ThreeWayMatchSession.create(
            company_id=data.company_id,
            purchase_order_snapshot=PurchaseOrderMatchSnapshot.capture(
                company_id=data.company_id,
                purchase_order_id=purchase_order.id,
                purchase_order_version=purchase_order.version,
                supplier_id=receipt.supplier_id,
                currency=purchase_order.currency,
                total_amount=purchase_order.total_amount,
                captured_at=captured_at,
            ),
            receiving_fiscal_snapshot=ReceivingFiscalMatchSnapshot.capture(
                company_id=data.company_id,
                goods_receipts=(VersionedArtifactReference(receipt.id, receipt.version),),
                fiscal_documents=(VersionedArtifactReference(inbound_id, 1),),
                supplier_id=receipt.supplier_id,
                currency=purchase_order.currency,
                invoiced_total_amount=purchase_order.total_amount,
                captured_at=captured_at,
            ),
            financial_snapshot=FinancialMatchSnapshot.capture(
                company_id=data.company_id,
                provisional_entry_id=provisional_entry_id,
                provisional_entry_version=1,
                payable_id=None,
                payable_version=None,
                supplier_id=receipt.supplier_id,
                currency=purchase_order.currency,
                obligation_amount=purchase_order.total_amount,
                captured_at=captured_at,
            ),
            tolerance_policy=MatchingTolerancePolicy.create(
                company_id=data.company_id,
                unit_price_variance_percentage="1",
                quantity_variance_percentage="1",
                rounding_absolute_limit="0.01",
            ),
            lines=(line,),
            created_by=data.actor_id,
            created_at=captured_at,
        )
        try:
            yield MatchingFixture(data, aggregate)
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(text("SET LOCAL erp.allow_matching_audit_cleanup = 'on'"))
                await session.execute(
                    delete(MatchingSessionModel).where(
                        MatchingSessionModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(InboundFiscalDocumentItemModel).where(
                        InboundFiscalDocumentItemModel.id == inbound_item_id
                    )
                )
                await session.execute(
                    delete(InboundFiscalDocumentModel).where(
                        InboundFiscalDocumentModel.id == inbound_id
                    )
                )
                await session.execute(
                    delete(ProvisionalEntryModel).where(
                        ProvisionalEntryModel.id == provisional_entry_id
                    )
                )


def test_matching_session_round_trip_preserves_snapshots_results_and_audit() -> None:
    async def scenario() -> None:
        async with matching_fixture() as fixture:
            data, pending = fixture.data, fixture.aggregate
            async with data.database.session() as session, session.begin():
                repository = ThreeWayMatchRepository(session, company_id=data.company_id)
                await repository.add(pending, actor_id=data.actor_id)
                assert await repository.get(pending.id) == pending
                assert await repository.list(status=ThreeWayMatchSessionStatus.PENDING) == (
                    pending,
                )
                assert await repository.list(
                    purchase_order_id=pending.purchase_order_snapshot.purchase_order.id
                ) == (pending,)

                running = pending.start(occurred_at=pending.created_at)
                assert await repository.save(running, actor_id=data.actor_id) == running
                matched = running.evaluate(occurred_at=running.started_at)
                assert await repository.save(matched, actor_id=data.actor_id) == matched
                assert await repository.get(pending.id) == matched

                audit = tuple(
                    await session.scalars(
                        select(MatchingAuditLogModel)
                        .where(
                            MatchingAuditLogModel.company_id == data.company_id,
                            MatchingAuditLogModel.matching_session_id == pending.id,
                        )
                        .order_by(MatchingAuditLogModel.aggregate_version)
                    )
                )
                assert [(item.from_status, item.to_status) for item in audit] == [
                    (None, "PENDING"),
                    ("PENDING", "RUNNING"),
                    ("RUNNING", "MATCHED"),
                ]
                assert [item.aggregate_version for item in audit] == [1, 2, 3]

    asyncio.run(scenario())


def test_discrepancy_override_round_trip_preserves_decision_and_line_report() -> None:
    async def scenario() -> None:
        async with matching_fixture() as fixture:
            data, pending = fixture.data, fixture.aggregate
            divergent_line = replace(
                pending.lines[0], invoiced_unit_price=pending.lines[0].invoiced_unit_price + 10
            )
            pending = replace(pending, lines=(divergent_line,))
            async with data.database.session() as session, session.begin():
                repository = ThreeWayMatchRepository(session, company_id=data.company_id)
                await repository.add(pending, actor_id=data.actor_id)
                running = pending.start(occurred_at=pending.created_at)
                await repository.save(running, actor_id=data.actor_id)
                discrepancy = running.evaluate(occurred_at=running.started_at)
                assert discrepancy.status is ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED
                await repository.save(discrepancy, actor_id=data.actor_id)
                overridden = discrepancy.override(
                    decided_by=data.actor_id,
                    workflow_instance_id=uuid4(),
                    reason="Aprovacao formal da divergencia comercial",
                    occurred_at=discrepancy.completed_at,
                )
                await repository.save(overridden, actor_id=data.actor_id)
                assert await repository.get(pending.id) == overridden

                persisted_item = await session.scalar(
                    select(MatchingSessionItemModel).where(
                        MatchingSessionItemModel.company_id == data.company_id,
                        MatchingSessionItemModel.matching_session_id == pending.id,
                    )
                )
                assert persisted_item is not None
                assert persisted_item.result_status == "PRICE_MISMATCH"
                assert persisted_item.reasons == ["UNIT_PRICE_TOLERANCE_EXCEEDED"]

    asyncio.run(scenario())


def test_repository_is_tenant_bound_and_translates_identity_and_version_conflicts() -> None:
    async def scenario() -> None:
        async with matching_fixture() as fixture:
            data, pending = fixture.data, fixture.aggregate
            async with data.database.session() as session, session.begin():
                repository = ThreeWayMatchRepository(session, company_id=data.company_id)
                await repository.add(pending, actor_id=data.actor_id)
                foreign = ThreeWayMatchRepository(session, company_id=data.other_company_id)
                assert await foreign.get(pending.id) is None
                with pytest.raises(MatchingScopeError):
                    await foreign.add(pending, actor_id=data.actor_id)

                savepoint = await session.begin_nested()
                with pytest.raises(MatchingSessionConflictError):
                    await repository.add(pending, actor_id=data.actor_id)
                await savepoint.rollback()

                running = pending.start(occurred_at=pending.created_at)
                await repository.save(running, actor_id=data.actor_id)
                with pytest.raises(MatchingVersionConflictError):
                    await repository.save(
                        running,
                        actor_id=data.actor_id,
                        expected_version=1,
                    )

    asyncio.run(scenario())


def test_repository_rejects_snapshot_drift_and_invalid_contract_inputs() -> None:
    async def scenario() -> None:
        async with matching_fixture() as fixture:
            data, pending = fixture.data, fixture.aggregate
            async with data.database.session() as session, session.begin():
                with pytest.raises(ValueError, match="company UUID"):
                    ThreeWayMatchRepository(session, company_id="invalid")  # type: ignore[arg-type]
                repository = ThreeWayMatchRepository(session, company_id=data.company_id)
                with pytest.raises(ValueError, match="actor UUID"):
                    await repository.add(pending, actor_id="invalid")  # type: ignore[arg-type]
                with pytest.raises(ValueError, match="pending"):
                    await repository.add(
                        pending.start(occurred_at=pending.created_at),
                        actor_id=data.actor_id,
                    )
                await repository.add(pending, actor_id=data.actor_id)
                running = pending.start(occurred_at=pending.created_at)
                changed_purchase = replace(
                    running.purchase_order_snapshot,
                    total_amount=running.purchase_order_snapshot.total_amount + 1,
                )
                with pytest.raises(InvalidMatchingSessionError, match="immutable"):
                    await repository.save(
                        replace(running, purchase_order_snapshot=changed_purchase),
                        actor_id=data.actor_id,
                    )
                with pytest.raises(ValueError, match="version increment"):
                    await repository.save(pending, actor_id=data.actor_id)
                with pytest.raises(ValueError, match="limit"):
                    await repository.list(limit=0)
                with pytest.raises(ValueError, match="offset"):
                    await repository.list(offset=-1)
                with pytest.raises(ValueError, match="official"):
                    await repository.list(status="PENDING")  # type: ignore[arg-type]
                with pytest.raises(ValueError, match="purchase_order_id"):
                    await repository.list(purchase_order_id="invalid")  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_migration_0041_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="procurement"))
                    matching_tables = {
                        "matching_session",
                        "matching_session_item",
                        "matching_audit_log",
                    }
                    assert matching_tables.issubset(tables) is expected
                    if not expected:
                        return
                    item_fks = inspector.get_foreign_keys(
                        "matching_session_item", schema="procurement"
                    )
                    assert any(
                        value["constrained_columns"] == ["company_id", "matching_session_id"]
                        for value in item_fks
                    )
                    session_fks = inspector.get_foreign_keys(
                        "matching_session", schema="procurement"
                    )
                    assert any(
                        value["constrained_columns"] == ["company_id", "purchase_order_id"]
                        for value in session_fks
                    )

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0040")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0041")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")

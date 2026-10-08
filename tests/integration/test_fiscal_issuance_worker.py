"""M11 issuance worker, SEFAZ outcomes and transactional event integration."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect, select

from erp.modules.fiscal.application import (
    CancelFiscalDocument,
    ContingencyMode,
    FiscalIssuanceStore,
    FiscalIssuanceWorker,
    FiscalWorkerMetadata,
    SefazEndpoint,
    SefazEnvironment,
    SefazGatewayPort,
    SefazSubmissionMode,
    SefazSubmissionResult,
    TransmitFiscalDocument,
)
from erp.modules.fiscal.domain import (
    FiscalAuthorizationStatus,
    FiscalDocument,
    FiscalDocumentStatus,
)
from erp.modules.fiscal.infrastructure import (
    ContingencyPolicy,
    FiscalDocumentRepository,
    PostgresFiscalIssuanceStore,
    ResilientSefazGateway,
    RetryPolicy,
    SefazMockAdapter,
    SefazMockScenario,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.test_fiscal_document_repository import fiscal_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class WorkerFixture:
    data: ProcurementFixture
    document: FiscalDocument


@asynccontextmanager
async def issuing_fixture() -> AsyncIterator[WorkerFixture]:
    async with fiscal_fixture() as (data, draft):
        issuing = draft.start_issuing()
        async with data.database.session() as session, session.begin():
            repository = FiscalDocumentRepository(session, company_id=data.company_id)
            await repository.add(draft, actor_id=data.actor_id)
            await repository.save(issuing, actor_id=data.actor_id, expected_version=1)
        try:
            yield WorkerFixture(data, issuing)
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(OutboxEventModel).where(OutboxEventModel.aggregate_id == issuing.id)
                )
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.entity_id == issuing.id)
                )


def metadata() -> FiscalWorkerMetadata:
    return FiscalWorkerMetadata(uuid4(), uuid4(), "127.0.0.1")


def endpoint() -> SefazEndpoint:
    return SefazEndpoint("SP", SefazEnvironment.HOMOLOGATION)


def transmission(
    fixture: WorkerFixture,
    *,
    mode: SefazSubmissionMode = SefazSubmissionMode.SYNCHRONOUS,
) -> TransmitFiscalDocument:
    return TransmitFiscalDocument(
        fixture.data.company_id,
        fixture.document.id,
        fixture.document.version,
        fixture.data.actor_id,
        access_key(fixture.document.model.value),
        b'<NFe><infNFe Id="NFe123"/></NFe>',
        "#NFe123",
        str(fixture.document.number).zfill(15),
        endpoint(),
        mode,
        metadata(),
    )


async def effects(data: ProcurementFixture, document_id: UUID) -> tuple[object, object]:
    async with data.database.session() as session:
        outbox = (
            await session.scalars(
                select(OutboxEventModel).where(OutboxEventModel.aggregate_id == document_id)
            )
        ).one()
        audit = (
            await session.scalars(
                select(AuditEventModel).where(AuditEventModel.entity_id == document_id)
            )
        ).one()
        return outbox, audit


def test_worker_authorizes_persists_final_xml_and_emits_atomic_effects() -> None:
    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            worker = FiscalIssuanceWorker(
                PostgresFiscalIssuanceStore(fixture.data.database), SefazMockAdapter()
            )
            saved = await worker.transmit(transmission(fixture))
            assert saved.status is FiscalDocumentStatus.AUTHORIZED
            assert saved.authorization_protocol == "135260000000001"
            assert saved.authorized_xml is not None
            assert saved.access_key == access_key()
            assert saved.sefaz_history[-1].status_code == "100"
            outbox, audit = await effects(fixture.data, saved.id)
            assert isinstance(outbox, OutboxEventModel)
            assert outbox.event_type == "FiscalDocumentAuthorized"
            assert outbox.payload["payload"]["integration_effects"] == [
                "inventory.effectuate",
                "finance.receivable.create",
            ]
            assert isinstance(audit, AuditEventModel)
            assert audit.operation == "FiscalDocumentAuthorized"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("scenario_value", "expected_status", "event_type", "code"),
    [
        (
            SefazMockScenario.REJECTED_DUPLICATE,
            FiscalDocumentStatus.REJECTED,
            "FiscalDocumentRejected",
            "204",
        ),
        (
            SefazMockScenario.REJECTED_DUPLICATE_KEY,
            FiscalDocumentStatus.REJECTED,
            "FiscalDocumentRejected",
            "539",
        ),
        (
            SefazMockScenario.DENIED_301,
            FiscalDocumentStatus.DENIED,
            "FiscalDocumentDenied",
            "301",
        ),
        (
            SefazMockScenario.DENIED_302,
            FiscalDocumentStatus.DENIED,
            "FiscalDocumentDenied",
            "302",
        ),
    ],
)
def test_worker_maps_unsuccessful_cstat_without_downstream_effects(
    scenario_value: SefazMockScenario,
    expected_status: FiscalDocumentStatus,
    event_type: str,
    code: str,
) -> None:
    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            worker = FiscalIssuanceWorker(
                PostgresFiscalIssuanceStore(fixture.data.database),
                SefazMockAdapter((scenario_value,)),
            )
            saved = await worker.transmit(transmission(fixture))
            assert saved.status is expected_status
            assert saved.rejection_code == code
            outbox, _ = await effects(fixture.data, saved.id)
            assert isinstance(outbox, OutboxEventModel)
            assert outbox.event_type == event_type
            assert outbox.payload["payload"]["integration_effects"] == []

    asyncio.run(scenario())


def test_worker_resolves_async_receipt_and_automatic_contingency() -> None:
    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            mock = SefazMockAdapter(
                (SefazMockScenario.UNAVAILABLE, SefazMockScenario.AUTHORIZED)
            )
            gateway = ResilientSefazGateway(
                mock,
                retry=RetryPolicy(max_attempts=1),
                contingency=ContingencyPolicy({"SP": ContingencyMode.SVC_AN}),
            )
            worker = FiscalIssuanceWorker(
                PostgresFiscalIssuanceStore(fixture.data.database), gateway
            )
            saved = await worker.transmit(transmission(fixture))
            assert saved.status is FiscalDocumentStatus.AUTHORIZED
            assert mock.calls[-1][1].contingency is ContingencyMode.SVC_AN

        async with issuing_fixture() as fixture:
            worker = FiscalIssuanceWorker(
                PostgresFiscalIssuanceStore(fixture.data.database), SefazMockAdapter()
            )
            saved = await worker.transmit(
                transmission(fixture, mode=SefazSubmissionMode.ASYNCHRONOUS)
            )
            assert saved.status is FiscalDocumentStatus.AUTHORIZED
            assert saved.sefaz_history[-1].status_code == "100"

    asyncio.run(scenario())


def test_cancellation_persists_event_xml_and_only_compensating_effects() -> None:
    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            store = PostgresFiscalIssuanceStore(fixture.data.database)
            worker = FiscalIssuanceWorker(store, SefazMockAdapter())
            authorized = await worker.transmit(transmission(fixture))
            command = CancelFiscalDocument(
                fixture.data.company_id,
                authorized.id,
                authorized.version,
                fixture.data.actor_id,
                "Cancelamento operacional autorizado",
                endpoint(),
                metadata(),
            )
            cancelled = await worker.cancel(command)
            assert cancelled.status is FiscalDocumentStatus.CANCELLED
            assert cancelled.cancellation_xml == "<procEventoNFe tpEvento='110111'/>"
            async with fixture.data.database.session() as session:
                events = list(
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(OutboxEventModel.aggregate_id == authorized.id)
                        .order_by(OutboxEventModel.occurred_at)
                    )
                )
            assert [event.event_type for event in events] == [
                "FiscalDocumentAuthorized",
                "FiscalDocumentCancelled",
            ]
            assert events[-1].payload["payload"]["integration_effects"] == [
                "inventory.reverse",
                "finance.receivable.reverse",
            ]

    asyncio.run(scenario())


def test_cancellation_window_and_rejection_leave_authorized_document_unchanged() -> None:
    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            store = PostgresFiscalIssuanceStore(fixture.data.database)
            worker = FiscalIssuanceWorker(store, SefazMockAdapter())
            authorized = await worker.transmit(transmission(fixture))
            command = CancelFiscalDocument(
                fixture.data.company_id,
                authorized.id,
                authorized.version,
                fixture.data.actor_id,
                "Cancelamento fora da janela legal",
                endpoint(),
                metadata(),
            )
            assert authorized.authorized_at is not None
            after_window = authorized.authorized_at + timedelta(hours=25)
            expired_worker = FiscalIssuanceWorker(
                store,
                SefazMockAdapter(),
                now=lambda: after_window,
            )
            with pytest.raises(ApplicationError) as expired:
                await expired_worker.cancel(command)
            assert expired.value.code == "FISCAL_CANCELLATION_WINDOW_EXPIRED"

            rejected_worker = FiscalIssuanceWorker(
                store, SefazMockAdapter((SefazMockScenario.REJECTED_DUPLICATE,))
            )
            with pytest.raises(ApplicationError) as rejected:
                await rejected_worker.cancel(command)
            assert rejected.value.code == "FISCAL_CANCELLATION_REJECTED"
            assert (await store.get(fixture.data.company_id, authorized.id)) == authorized

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_fiscal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_enqueue(*_: object, **__: object) -> UUID:
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(OutboxService, "enqueue", fail_enqueue)

    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            store = PostgresFiscalIssuanceStore(fixture.data.database)
            worker = FiscalIssuanceWorker(store, SefazMockAdapter())
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await worker.transmit(transmission(fixture))
            persisted = await store.get(fixture.data.company_id, fixture.document.id)
            assert persisted is not None
            assert persisted.status is FiscalDocumentStatus.ISSUING
            assert persisted.version == fixture.document.version

    asyncio.run(scenario())


def test_worker_guards_scope_state_version_model_and_window_configuration() -> None:
    with pytest.raises(ValueError, match="window"):
        FiscalIssuanceWorker(
            cast(FiscalIssuanceStore, object()),
            cast(SefazGatewayPort, object()),
            cancellation_window=timedelta(0),
        )

    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            store = PostgresFiscalIssuanceStore(fixture.data.database)
            worker = FiscalIssuanceWorker(store, SefazMockAdapter())
            base = transmission(fixture)
            with pytest.raises(ApplicationError) as missing:
                await worker.transmit(replace(base, document_id=uuid4()))
            assert missing.value.code == "RESOURCE_NOT_FOUND"
            with pytest.raises(ApplicationError) as stale:
                await worker.transmit(replace(base, expected_version=99))
            assert stale.value.code == "VERSION_CONFLICT"
            with pytest.raises(ApplicationError) as wrong_model:
                await worker.transmit(replace(base, access_key=access_key("65")))
            assert wrong_model.value.code == "BUSINESS_VALIDATION_ERROR"

            cancellation = CancelFiscalDocument(
                fixture.data.company_id,
                fixture.document.id,
                fixture.document.version,
                fixture.data.actor_id,
                "Cancelamento operacional autorizado",
                endpoint(),
                metadata(),
            )
            with pytest.raises(ApplicationError) as invalid_state:
                await worker.cancel(cancellation)
            assert invalid_state.value.code == "INVALID_STATE_TRANSITION"

            authorized = await worker.transmit(base)
            with pytest.raises(ApplicationError) as stale_cancel:
                await worker.cancel(replace(cancellation, expected_version=1))
            assert stale_cancel.value.code == "VERSION_CONFLICT"
            with pytest.raises(ApplicationError) as retransmit:
                await worker.transmit(replace(base, expected_version=authorized.version))
            assert retransmit.value.code == "INVALID_STATE_TRANSITION"

    asyncio.run(scenario())


def test_worker_rejects_pending_receipt_without_identifier() -> None:
    class PendingGateway(SefazMockAdapter):
        async def submit_batch(self, request_value: object) -> SefazSubmissionResult:
            del request_value
            return SefazSubmissionResult(
                FiscalAuthorizationStatus.PENDING,
                "103",
                "Lote recebido",
                endpoint(),
                "1",
            )

    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            worker = FiscalIssuanceWorker(
                PostgresFiscalIssuanceStore(fixture.data.database), PendingGateway()
            )
            with pytest.raises(RuntimeError, match="receipt number"):
                await worker.transmit(transmission(fixture))

    asyncio.run(scenario())


def test_store_rejects_incomplete_unknown_and_stale_sefaz_results() -> None:
    async def scenario() -> None:
        async with issuing_fixture() as fixture:
            store = PostgresFiscalIssuanceStore(fixture.data.database)
            command_value = transmission(fixture)
            incomplete = SefazSubmissionResult(
                FiscalAuthorizationStatus.AUTHORIZED,
                "100",
                "Autorizado",
                endpoint(),
                command_value.batch_id,
            )
            with pytest.raises(ApplicationError) as invalid:
                await store.complete_issuance(command_value, incomplete)
            assert invalid.value.code == "INVALID_SEFAZ_RESPONSE"

            unknown = SefazSubmissionResult(
                FiscalAuthorizationStatus.UNKNOWN,
                "999",
                "Resposta desconhecida",
                endpoint(),
                command_value.batch_id,
            )
            with pytest.raises(ApplicationError) as unsupported:
                await store.complete_issuance(command_value, unknown)
            assert unsupported.value.code == "UNSUPPORTED_SEFAZ_RESPONSE"

            with pytest.raises(ApplicationError) as missing:
                await store.complete_issuance(replace(command_value, document_id=uuid4()), unknown)
            assert missing.value.code == "RESOURCE_NOT_FOUND"

            with pytest.raises(ApplicationError) as stale:
                await store.complete_issuance(replace(command_value, expected_version=99), unknown)
            assert stale.value.code == "VERSION_CONFLICT"

    asyncio.run(scenario())


def test_migration_0036_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_columns(sync_connection: Connection) -> None:
                    names = {
                        value["name"]
                        for value in inspect(sync_connection).get_columns(
                            "fiscal_document", schema="fiscal"
                        )
                    }
                    assert ("authorized_xml" in names) is expected
                    assert ("cancellation_xml" in names) is expected

                await connection.run_sync(inspect_columns)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0035")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0036")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")

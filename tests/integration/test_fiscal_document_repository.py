"""M11 fiscal document repository integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect
from sqlalchemy.exc import IntegrityError

from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentConflictError,
    FiscalDocumentStatus,
    FiscalScopeError,
    FiscalVersionConflictError,
    SefazResponseSnapshot,
)
from erp.modules.fiscal.infrastructure import (
    FiscalDocumentItemModel,
    FiscalDocumentRepository,
)
from erp.modules.fiscal.infrastructure import (
    FiscalDocumentModel as FiscalDocumentRecord,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_procurement_supplier_repository import (
    ProcurementFixture,
    procurement_fixture,
)
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key, draft

pytestmark = pytest.mark.integration


@asynccontextmanager
async def fiscal_fixture() -> AsyncIterator[tuple[ProcurementFixture, FiscalDocument]]:
    async with procurement_fixture() as data:
        document = replace(draft(), company_id=data.company_id)
        try:
            yield data, document
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(FiscalDocumentItemModel).where(
                        FiscalDocumentItemModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )
                await session.execute(
                    delete(FiscalDocumentRecord).where(
                        FiscalDocumentRecord.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )


def test_fiscal_document_round_trip_preserves_snapshots_and_sefaz_history() -> None:
    async def scenario() -> None:
        async with (
            fiscal_fixture() as (data, document),
            data.database.session() as session,
            session.begin(),
        ):
            repository = FiscalDocumentRepository(session, company_id=data.company_id)
            await repository.add(document, actor_id=data.actor_id)
            assert await repository.list(status=FiscalDocumentStatus.DRAFT) == (document,)
            assert await repository.list() == (document,)
            assert await repository.get(document.id) == document

            response = SefazResponseSnapshot(
                attempt_id=uuid4(),
                status_code=" 103 ",
                message=" Lote recebido ",
                occurred_at=datetime.now(UTC),
                protocol=" ",
            )
            issuing = replace(document.start_issuing(), sefaz_history=(response,))
            assert await repository.save(issuing, actor_id=data.actor_id) == issuing
            authorized = issuing.authorize(
                access_key=access_key(),
                protocol="135260000000001",
                authorized_at=datetime.now(UTC),
            )
            await repository.save(authorized, actor_id=data.actor_id)

            restored = await repository.get(document.id)
            assert restored == authorized
            assert restored is not None
            assert restored.items[0].tax_snapshot == document.items[0].tax_snapshot
            assert restored.issuer == document.issuer
            assert restored.recipient == document.recipient
            assert restored.sefaz_history[0].status_code == "103"
            assert restored.sefaz_history[0].protocol is None
            assert await repository.list(status=FiscalDocumentStatus.AUTHORIZED) == (authorized,)
            cancelled = authorized.cancel(
                protocol="135260000000002", cancelled_at=datetime.now(UTC)
            )
            await repository.save(cancelled, actor_id=data.actor_id)
            assert await repository.get(document.id) == cancelled

            rejected_draft = replace(
                document,
                id=uuid4(),
                number=document.number + 1,
                items=tuple(replace(item, id=uuid4()) for item in document.items),
            )
            await repository.add(rejected_draft, actor_id=data.actor_id)
            rejected_issuing = rejected_draft.start_issuing()
            await repository.save(rejected_issuing, actor_id=data.actor_id)
            rejected = rejected_issuing.reject(code="539", reason="Duplicidade")
            await repository.save(rejected, actor_id=data.actor_id)
            assert await repository.get(rejected.id) == rejected

    asyncio.run(scenario())


def test_fiscal_repository_is_tenant_bound_and_translates_duplicate_identity() -> None:
    async def scenario() -> None:
        async with (
            fiscal_fixture() as (data, document),
            data.database.session() as session,
            session.begin(),
        ):
            repository = FiscalDocumentRepository(session, company_id=data.company_id)
            await repository.add(document, actor_id=data.actor_id)
            assert (
                await FiscalDocumentRepository(session, company_id=data.other_company_id).get(
                    document.id
                )
                is None
            )
            with pytest.raises(FiscalScopeError):
                await FiscalDocumentRepository(session, company_id=data.other_company_id).add(
                    document, actor_id=data.actor_id
                )
            duplicate = replace(document, id=uuid4())
            savepoint = await session.begin_nested()
            with pytest.raises(FiscalDocumentConflictError):
                await repository.add(duplicate, actor_id=data.actor_id)
            await savepoint.rollback()

    asyncio.run(scenario())


def test_fiscal_access_key_is_unique_and_stale_writes_are_rejected() -> None:
    async def scenario() -> None:
        async with (
            fiscal_fixture() as (data, first),
            data.database.session() as session,
            session.begin(),
        ):
            second = replace(
                first,
                id=uuid4(),
                number=first.number + 1,
                items=tuple(replace(item, id=uuid4()) for item in first.items),
            )
            repository = FiscalDocumentRepository(session, company_id=data.company_id)
            await repository.add(first, actor_id=data.actor_id)
            await repository.add(second, actor_id=data.actor_id)
            first_issuing = first.start_issuing()
            await repository.save(first_issuing, actor_id=data.actor_id)
            with pytest.raises(FiscalVersionConflictError):
                await repository.save(
                    first_issuing,
                    actor_id=data.actor_id,
                    expected_version=1,
                )

            second_issuing = second.start_issuing()
            await repository.save(second_issuing, actor_id=data.actor_id)
            now = datetime.now(UTC)
            first_authorized = first_issuing.authorize(
                access_key=access_key(), protocol="1", authorized_at=now
            )
            await repository.save(first_authorized, actor_id=data.actor_id)
            second_authorized = second_issuing.authorize(
                access_key=access_key(), protocol="2", authorized_at=now
            )
            savepoint = await session.begin_nested()
            with pytest.raises(FiscalDocumentConflictError):
                await repository.save(second_authorized, actor_id=data.actor_id)
            await savepoint.rollback()

    asyncio.run(scenario())


def test_fiscal_repository_requires_explicit_scope_version_and_pagination() -> None:
    async def scenario() -> None:
        async with (
            fiscal_fixture() as (data, document),
            data.database.session() as session,
            session.begin(),
        ):
            with pytest.raises(ValueError, match="company UUID"):
                FiscalDocumentRepository(session, company_id="invalid")  # type: ignore[arg-type]
            repository = FiscalDocumentRepository(session, company_id=data.company_id)
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.add(document, actor_id="invalid")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="start draft"):
                await repository.add(document.start_issuing(), actor_id=data.actor_id)
            await repository.add(document, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="version increment"):
                await repository.save(document, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="limit"):
                await repository.list(limit=0)
            with pytest.raises(ValueError, match="offset"):
                await repository.list(offset=-1)
            with pytest.raises(ValueError, match="official fiscal"):
                await repository.list(status="DRAFT")  # type: ignore[arg-type]

            unexpected = IntegrityError("statement", {}, RuntimeError("database error"))
            with pytest.raises(IntegrityError) as captured:
                repository._translate(unexpected)
            assert captured.value is unexpected

    asyncio.run(scenario())


def test_migration_0035_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    schemas = set(inspect(sync_connection).get_schema_names())
                    assert ("fiscal" in schemas) is expected
                    if expected:
                        inspector = inspect(sync_connection)
                        tables = set(inspector.get_table_names(schema="fiscal"))
                        assert tables == {"fiscal_document", "fiscal_document_item"}
                        foreign_keys = inspector.get_foreign_keys(
                            "fiscal_document_item", schema="fiscal"
                        )
                        assert any(
                            value["constrained_columns"]
                            == ["company_id", "fiscal_document_id"]
                            for value in foreign_keys
                        )
                        unique_names = {
                            value["name"]
                            for value in inspector.get_unique_constraints(
                                "fiscal_document", schema="fiscal"
                            )
                        }
                        assert {
                            "uq_fiscal_document_company_series_number",
                            "uq_fiscal_document_access_key",
                        } <= unique_names

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0034")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0035")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")

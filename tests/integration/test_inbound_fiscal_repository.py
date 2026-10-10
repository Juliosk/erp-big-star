"""Inbound fiscal repository integration against PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect

from erp.modules.fiscal.application import InboundNFeParser
from erp.modules.fiscal.domain import FiscalScopeError, FiscalVersionConflictError
from erp.modules.fiscal.infrastructure import (
    InboundFiscalDocumentItemModel,
    InboundFiscalDocumentModel,
    InboundFiscalDocumentRepository,
    MdeEventModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_procurement_supplier_repository import (
    ProcurementFixture,
    procurement_fixture,
)
from tests.unit.modules.fiscal.application.test_inbound_fiscal import inbound_xml

pytestmark = pytest.mark.integration


@asynccontextmanager
async def inbound_fixture() -> AsyncIterator[ProcurementFixture]:
    async with procurement_fixture() as data:
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                for model in (
                    MdeEventModel,
                    InboundFiscalDocumentItemModel,
                    InboundFiscalDocumentModel,
                ):
                    await session.execute(
                        delete(model).where(
                            model.company_id.in_((data.company_id, data.other_company_id))
                        )
                    )


def test_inbound_repository_round_trip_tenant_scope_and_optimistic_version() -> None:
    async def scenario() -> None:
        async with inbound_fixture() as data, data.database.session() as session, session.begin():
            document = InboundNFeParser().parse(data.company_id, inbound_xml())
            repository = InboundFiscalDocumentRepository(session, company_id=data.company_id)
            await repository.add(document, actor_id=data.actor_id)
            assert await repository.get(document.id) == document
            assert await repository.get_by_access_key(str(document.access_key)) == document
            assert await repository.list(supplier_tax_id=document.supplier.tax_id) == (document,)
            assert (
                await InboundFiscalDocumentRepository(
                    session, company_id=data.other_company_id
                ).get(document.id)
                is None
            )
            with pytest.raises(FiscalScopeError):
                await InboundFiscalDocumentRepository(
                    session, company_id=data.other_company_id
                ).add(document, actor_id=data.actor_id)
            with pytest.raises(FiscalVersionConflictError):
                await repository.save(
                    replace(document, version=3), actor_id=data.actor_id, expected_version=2
                )

    asyncio.run(scenario())


def test_inbound_repository_requires_explicit_uuid_scope() -> None:
    async def scenario() -> None:
        async with inbound_fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match="company UUID"):
                InboundFiscalDocumentRepository(session, company_id="invalid")  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_migration_0037_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="fiscal"))
                    inbound = {
                        "inbound_fiscal_document",
                        "inbound_fiscal_document_item",
                        "mde_event",
                    }
                    assert inbound.issubset(tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0036")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0037")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")

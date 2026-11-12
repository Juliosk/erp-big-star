"""Migration 0061 contract against real PostgreSQL."""

import asyncio
from importlib import import_module
from typing import cast

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Table, inspect

from erp.modules.finance.infrastructure import (
    PaymentRequestItemModel,
    PaymentRequestModel,
)
from erp.modules.fiscal.infrastructure import TaxRuleModel
from erp.modules.procurement.infrastructure import (
    RequestForQuotationItemModel,
    RequestForQuotationModel,
    RequestForQuotationQuoteLineModel,
    RequestForQuotationSupplierModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Base, Database

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "finance": {"payment_request", "payment_request_item"},
    "fiscal": {"tax_rule"},
    "procurement": {
        "request_for_quotation",
        "rfq_item",
        "rfq_supplier",
        "rfq_supplier_quote_line",
    },
}
TARGET_TABLES = {(schema, table) for schema, tables in EXPECTED_TABLES.items() for table in tables}
TARGET_MODELS = (
    PaymentRequestItemModel,
    PaymentRequestModel,
    TaxRuleModel,
    RequestForQuotationItemModel,
    RequestForQuotationModel,
    RequestForQuotationQuoteLineModel,
    RequestForQuotationSupplierModel,
)


def test_migration_0061_is_reversible_and_tenant_bound_on_postgresql() -> None:
    configuration = Config("alembic.ini")
    assert {
        (
            cast(Table, model.__table__).schema,
            cast(Table, model.__table__).name,
        )
        for model in TARGET_MODELS
    } == TARGET_TABLES

    async def verify(revision: str, *, tables_exist: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    migration_context = MigrationContext.configure(sync_connection)
                    assert migration_context.get_current_heads() == (revision,)
                    for schema, expected_tables in EXPECTED_TABLES.items():
                        tables = set(inspector.get_table_names(schema=schema))
                        if tables_exist:
                            assert expected_tables.issubset(tables)
                        else:
                            assert expected_tables.isdisjoint(tables)
                    if not tables_exist:
                        return
                    tax_uniques = {
                        value["name"]
                        for value in inspector.get_unique_constraints("tax_rule", schema="fiscal")
                    }
                    assert "uq_tax_rule_company_code_version" in tax_uniques
                    rfq_item_fks = inspector.get_foreign_keys("rfq_item", schema="procurement")
                    assert ("company_id", "rfq_id") in {
                        tuple(value["constrained_columns"]) for value in rfq_item_fks
                    }
                    request_item_fks = inspector.get_foreign_keys(
                        "payment_request_item", schema="finance"
                    )
                    constrained = {
                        tuple(value["constrained_columns"]) for value in request_item_fks
                    }
                    assert ("company_id", "payment_request_id") in constrained
                    assert ("company_id", "payable_id", "installment_id") in constrained
                    assert ("company_id", "matching_session_id") in constrained
                    for model in TARGET_MODELS:
                        table = cast(Table, model.__table__)
                        columns = {
                            column["name"]
                            for column in inspector.get_columns(table.name, schema=table.schema)
                        }
                        assert columns == set(table.columns.keys())

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0060")
        asyncio.run(verify("0060", tables_exist=False))
        command.upgrade(configuration, "0061")
        asyncio.run(verify("0061", tables_exist=True))
    finally:
        command.upgrade(configuration, "head")


def test_migration_head_matches_erp_orm_across_schemas() -> None:
    # Load the ORM mappings used by the API composition root even when run in isolation.
    import_module("erp.apps.api.app")
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    assert head is not None

    def verify(connection: Connection) -> None:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        assert context.get_current_heads() == (head,)
        assert compare_metadata(context, Base.metadata) == []

    async def compare() -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:
                await connection.run_sync(verify)
        finally:
            await database.dispose()

    asyncio.run(compare())

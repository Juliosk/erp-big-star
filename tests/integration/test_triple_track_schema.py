"""Migration 0061 contract against real PostgreSQL."""

import asyncio
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
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
from erp.platform.database import Database

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

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    for schema, expected_tables in EXPECTED_TABLES.items():
                        tables = set(inspector.get_table_names(schema=schema))
                        assert expected_tables.issubset(tables) is expected
                    if not expected:
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
        asyncio.run(verify(False))
        command.upgrade(configuration, "0061")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")

"""Inspect M15 migration and ORM metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from erp.modules.admin.infrastructure import CompanyModel
from erp.modules.customer.infrastructure import CustomerModel
from erp.modules.inventory.infrastructure import InventoryReservationModel
from erp.modules.pricing.infrastructure import PricingSnapshotModel
from erp.modules.product.infrastructure import ProductModel
from erp.modules.sales.infrastructure import (
    QuoteRevisionItemModel,
    QuoteRevisionModel,
    SalesOrderReservationLineModel,
    SalesOrderReservationModel,
    SalesQuoteModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_sales(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    return kind != "table" or obj.schema == "sales_b2b"


@pytest.mark.integration
def test_sales_quote_migration_matches_orm_and_tenant_fks() -> None:
    def verify(connection: Connection) -> None:
        assert CompanyModel.__table__.schema == "admin"
        assert CustomerModel.__table__.schema == "crm"
        assert ProductModel.__table__.schema == "product"
        assert PricingSnapshotModel.__table__.schema == "pricing"
        assert InventoryReservationModel.__table__.schema == "inventory"
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="sales_b2b")) >= {
            "sales_quote",
            "quote_revision",
            "quote_revision_item",
            "sales_order_reservation",
            "sales_order_reservation_line",
        }
        for table, model in (
            ("sales_quote", SalesQuoteModel),
            ("quote_revision", QuoteRevisionModel),
            ("quote_revision_item", QuoteRevisionItemModel),
            ("sales_order_reservation", SalesOrderReservationModel),
            ("sales_order_reservation_line", SalesOrderReservationLineModel),
        ):
            columns = {
                column["name"] for column in inspector.get_columns(table, schema="sales_b2b")
            }
            assert columns == set(model.__table__.columns.keys())
        quote_fks = inspector.get_foreign_keys("sales_quote", "sales_b2b")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in quote_fks
        } == {("company_id",): "admin", ("company_id", "customer_id"): "crm"}
        item_fks = inspector.get_foreign_keys("quote_revision_item", "sales_b2b")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in item_fks
        } == {
            ("company_id", "revision_id"): "sales_b2b",
            ("company_id", "product_id"): "product",
            ("company_id", "pricing_snapshot_id"): "pricing",
        }
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_sales,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        assert compare_metadata(context, Base.metadata) == []

    async def scenario() -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:
                await connection.run_sync(verify)
        finally:
            await database.dispose()

    asyncio.run(scenario())

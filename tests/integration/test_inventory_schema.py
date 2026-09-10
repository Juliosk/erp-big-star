"""Inspect the M5 physical inventory migration and ORM metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, text

from erp.modules.admin.infrastructure import BranchModel, CompanyModel
from erp.modules.inventory.infrastructure import (
    InventoryLotModel,
    InventoryPoolModel,
    InventoryPostingModel,
    InventoryTransactionModel,
    WarehouseLocationModel,
    WarehouseModel,
)
from erp.modules.product.infrastructure import ProductModel
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_inventory(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    """Compare only the M5 schema owned by this sprint."""
    return kind != "table" or obj.schema == "inventory"


@pytest.mark.integration
def test_inventory_foundation_migration_matches_orm_and_tenant_fks() -> None:
    def verify(connection: Connection) -> None:
        assert CompanyModel.__table__.schema == "admin"
        assert BranchModel.__table__.schema == "admin"
        assert ProductModel.__table__.schema == "product"
        assert WarehouseModel.__table__.schema == "inventory"
        assert WarehouseLocationModel.__table__.schema == "inventory"
        assert InventoryPoolModel.__table__.schema == "inventory"
        assert InventoryLotModel.__table__.schema == "inventory"
        assert InventoryTransactionModel.__table__.schema == "inventory"
        assert InventoryPostingModel.__table__.schema == "inventory"
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="inventory")) >= {
            "warehouse",
            "location",
            "inventory_pool",
            "inventory_lot",
            "inventory_transaction",
            "inventory_posting",
        }
        warehouse_columns = {
            column["name"]: column for column in inspector.get_columns("warehouse", "inventory")
        }
        assert set(warehouse_columns) == set(WarehouseModel.__table__.columns.keys())
        assert all(not column["nullable"] for column in warehouse_columns.values())
        location_columns = {
            column["name"]: column for column in inspector.get_columns("location", "inventory")
        }
        assert set(location_columns) == set(WarehouseLocationModel.__table__.columns.keys())
        assert location_columns["parent_location_id"]["nullable"]
        pool_columns = {
            column["name"]: column
            for column in inspector.get_columns("inventory_pool", "inventory")
        }
        assert set(pool_columns) == set(InventoryPoolModel.__table__.columns.keys())
        lot_columns = {
            column["name"]: column for column in inspector.get_columns("inventory_lot", "inventory")
        }
        assert set(lot_columns) == set(InventoryLotModel.__table__.columns.keys())
        assert lot_columns["expires_on"]["nullable"]
        transaction_columns = {
            column["name"]: column
            for column in inspector.get_columns("inventory_transaction", "inventory")
        }
        assert set(transaction_columns) == set(InventoryTransactionModel.__table__.columns.keys())
        posting_columns = {
            column["name"]: column
            for column in inspector.get_columns("inventory_posting", "inventory")
        }
        assert set(posting_columns) == set(InventoryPostingModel.__table__.columns.keys())
        triggers = set(
            connection.execute(
                text(
                    """
                    SELECT trigger_name
                    FROM information_schema.triggers
                    WHERE event_object_schema = 'inventory'
                      AND event_object_table IN ('inventory_transaction', 'inventory_posting')
                    """
                )
            ).scalars()
        )
        assert {
            "trg_inventory_transaction_append_only_update",
            "trg_inventory_transaction_append_only_delete",
            "trg_inventory_posting_append_only_update",
            "trg_inventory_posting_append_only_delete",
        }.issubset(triggers)
        lot_foreign_keys = inspector.get_foreign_keys("inventory_lot", "inventory")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in lot_foreign_keys
        } == {("company_id", "product_id"): "product"}
        location_foreign_keys = inspector.get_foreign_keys("location", "inventory")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in location_foreign_keys
        } == {
            ("company_id", "warehouse_id"): "inventory",
            ("company_id", "parent_location_id"): "inventory",
        }
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_inventory,
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

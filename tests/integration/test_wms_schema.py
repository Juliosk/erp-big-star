"""Inspect the M10 WMS migration and ORM metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from erp.modules.admin.infrastructure import CompanyModel
from erp.modules.inventory.infrastructure import InventoryLotModel, WarehouseModel
from erp.modules.product.infrastructure import ProductModel
from erp.modules.wms.infrastructure import (
    PackageItemModel,
    PackageModel,
    PickingTaskModel,
    PickingWaveModel,
    ShipmentModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_wms(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    """Compare only the M10 schema owned by this sprint."""
    return kind != "table" or obj.schema == "wms"


@pytest.mark.integration
def test_wms_foundation_migration_matches_orm_and_tenant_fks() -> None:
    def verify(connection: Connection) -> None:
        assert CompanyModel.__table__.schema == "admin"
        assert ProductModel.__table__.schema == "product"
        assert WarehouseModel.__table__.schema == "inventory"
        assert InventoryLotModel.__table__.schema == "inventory"
        assert PickingWaveModel.__table__.schema == "wms"
        assert PickingTaskModel.__table__.schema == "wms"
        assert ShipmentModel.__table__.schema == "wms"
        assert PackageModel.__table__.schema == "wms"
        assert PackageItemModel.__table__.schema == "wms"
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="wms")) >= {
            "picking_wave",
            "picking_task",
            "shipment",
            "package",
            "package_item",
        }
        for table, model in (
            ("picking_wave", PickingWaveModel),
            ("picking_task", PickingTaskModel),
            ("shipment", ShipmentModel),
            ("package", PackageModel),
            ("package_item", PackageItemModel),
        ):
            columns = {column["name"]: column for column in inspector.get_columns(table, "wms")}
            assert set(columns) == set(model.__table__.columns.keys())
        wave_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("picking_wave", "wms")
        }
        assert "uq_wms_picking_wave_company_code" in wave_uniques
        task_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("picking_task", "wms")
        }
        assert "uq_wms_picking_task_wave_sequence" in task_uniques
        package_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("package", "wms")
        }
        assert "uq_wms_package_company_code" in package_uniques
        shipment_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("shipment", "wms")
        }
        assert "uq_wms_shipment_company_code" in shipment_uniques
        task_foreign_keys = inspector.get_foreign_keys("picking_task", "wms")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in task_foreign_keys
        } == {
            ("company_id", "wave_id"): "wms",
            ("company_id", "product_id"): "product",
            ("company_id", "warehouse_id"): "inventory",
            ("company_id", "lot_id"): "inventory",
            ("company_id", "pool_id"): "inventory",
        }
        package_item_foreign_keys = inspector.get_foreign_keys("package_item", "wms")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in package_item_foreign_keys
        } == {
            ("company_id", "package_id"): "wms",
            ("company_id", "task_id"): "wms",
            ("company_id", "product_id"): "product",
            ("company_id", "lot_id"): "inventory",
        }
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_wms,
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

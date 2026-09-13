"""Inspect the M9 pricing migration and ORM metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from erp.modules.admin.infrastructure import CompanyModel
from erp.modules.pricing.infrastructure import (
    MinimumMarginPolicyModel,
    PriceListItemModel,
    PriceListModel,
    PriceListVersionModel,
    PricingSnapshotModel,
)
from erp.modules.product.infrastructure import ProductModel
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_pricing(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    """Compare only the M9 schema owned by this sprint."""
    return kind != "table" or obj.schema == "pricing"


@pytest.mark.integration
def test_pricing_foundation_migration_matches_orm_and_tenant_fks() -> None:
    def verify(connection: Connection) -> None:
        assert CompanyModel.__table__.schema == "admin"
        assert ProductModel.__table__.schema == "product"
        assert PriceListModel.__table__.schema == "pricing"
        assert PriceListVersionModel.__table__.schema == "pricing"
        assert PriceListItemModel.__table__.schema == "pricing"
        assert MinimumMarginPolicyModel.__table__.schema == "pricing"
        assert PricingSnapshotModel.__table__.schema == "pricing"
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="pricing")) >= {
            "price_list",
            "price_list_version",
            "price_list_item",
            "minimum_margin_policy",
            "pricing_snapshot",
        }
        for table, model in (
            ("price_list", PriceListModel),
            ("price_list_version", PriceListVersionModel),
            ("price_list_item", PriceListItemModel),
            ("minimum_margin_policy", MinimumMarginPolicyModel),
            ("pricing_snapshot", PricingSnapshotModel),
        ):
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table, schema="pricing")
            }
            assert set(columns) == set(model.__table__.columns.keys())
        price_list_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("price_list", "pricing")
        }
        assert "uq_price_list_company_code" in price_list_uniques
        version_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("price_list_version", "pricing")
        }
        assert "uq_price_list_version_number" in version_uniques
        item_foreign_keys = inspector.get_foreign_keys("price_list_item", "pricing")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in item_foreign_keys
        } == {
            ("company_id", "price_list_version_id"): "pricing",
            ("company_id", "product_id"): "product",
        }
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_pricing,
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

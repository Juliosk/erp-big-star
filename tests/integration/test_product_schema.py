"""Inspect the real migration, including non-default-schema metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from erp.modules.admin.infrastructure import CompanyModel
from erp.modules.product.infrastructure import ProductModel
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_product(obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any) -> bool:
    """Compare only the owner changed by this migration, not unrelated schema debt."""
    return kind != "table" or obj.schema == "product"


@pytest.mark.integration
def test_product_migration_matches_orm_and_foundation_fk() -> None:
    def verify(connection: Connection) -> None:
        assert (
            CompanyModel.__table__.schema == "admin"
        )  # Composition registers Foundation metadata.
        assert ProductModel.__table__.schema == "product"
        inspector = inspect(connection)
        columns = {column["name"]: column for column in inspector.get_columns("product", "product")}
        assert set(columns) == set(ProductModel.__table__.columns.keys())
        assert all(not column["nullable"] for column in columns.values())
        checks = inspector.get_check_constraints("product", "product")
        assert {check["name"] for check in checks} == {
            "ck_product_code_format",
            "ck_product_sku_format",
            "ck_product_uom_format",
            "ck_product_name_length",
            "ck_product_type",
            "ck_product_lifecycle",
            "ck_product_version_positive",
        }
        foreign_keys = inspector.get_foreign_keys("product", "product")
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["referred_schema"] == "admin"
        assert foreign_keys[0]["referred_table"] == "company"
        assert foreign_keys[0]["options"]["ondelete"] == "RESTRICT"
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_product,
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

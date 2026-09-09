"""The public M2 bulk port works without an M23 repository or HTTP endpoint."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from erp.modules.admin.contracts import CompanyAccessService, PermissionCode
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.product.contracts import CommandMetadata, ProductAuthorization, ProductImportRow
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.product.infrastructure.product_imports import PostgresProductImports
from erp.platform.errors import ApplicationError
from tests.integration.product_api_support import product_api

pytestmark = pytest.mark.integration


def test_owner_bulk_validation_effects_noop_and_defensive_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with product_api() as fixture:
        assert fixture.resolver.context is not None
        context = replace(
            fixture.resolver.context,
            permissions=frozenset(
                PermissionCode(code)
                for code in (
                    "product.product.read",
                    "product.product.create",
                    "product.product.update",
                )
            ),
        )

        async def scenario() -> None:
            authorization = ProductAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(fixture.data.database))
            )
            async with fixture.data.database.session() as session, session.begin():
                owner = PostgresProductImports(
                    session,
                    fixture.data.company_id,
                    context,
                    authorization,
                    CommandMetadata(uuid4(), uuid4()),
                )
                row = ProductImportRow(
                    2,
                    {
                        "code": "OWN",
                        "sku": uuid4().hex,
                        "name": "Owner",
                        "product_type": "PA",
                        "uom": "UN",
                    },
                )
                plans = await owner.validate((row,))
                await owner.authorize(plans)
                assert await owner.commit(plans) == 1
                unchanged = await owner.validate((row,))
                assert await owner.commit(unchanged) == 0
                updated = ProductImportRow(2, {**row.values, "name": "Changed", "uom": "CX"})
                plans = await owner.validate((updated,))
                await owner.authorize(plans)
                assert await owner.commit(plans) == 1
                invalid = ProductImportRow(
                    3, {**row.values, "code": "OTHER", "product_type": "KIT"}
                )
                assert (await owner.validate((invalid,)))[0].errors == (
                    "IMMUTABLE_PRODUCT_IDENTITY",
                )
                invalid_new = ProductImportRow(
                    3, {**row.values, "sku": uuid4().hex, "product_type": "INVALID"}
                )
                assert (await owner.validate((invalid_new,)))[0].errors == (
                    "INVALID_PRODUCT_FIELDS",
                )
                collision = ProductImportRow(3, {**row.values, "sku": uuid4().hex})
                assert (
                    "PRODUCT_IDENTIFIER_CONFLICT" in (await owner.validate((collision,)))[0].errors
                )
                assert (
                    "DUPLICATE_FILE_IDENTIFIER"
                    in (await owner.validate((updated, updated)))[1].errors
                )
                with pytest.raises(ApplicationError, match="changed"):
                    await owner.commit(plans)
                missing = await owner.validate((row,))
                with monkeypatch.context() as patch:
                    patch.setattr(ProductRepository, "get", AsyncMock(return_value=None))
                    with pytest.raises(ApplicationError, match="missing"):
                        await owner.commit(missing)

        assert fixture.client.portal is not None
        fixture.client.portal.call(scenario)

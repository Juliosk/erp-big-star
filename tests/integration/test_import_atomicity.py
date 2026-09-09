from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.admin.contracts import PermissionCode
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.product.infrastructure.product_effects import ProductEffects
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from tests.integration.import_api_support import command, import_api, upload
from tests.integration.minio_support import minio_storage

pytestmark = pytest.mark.integration


def test_real_minio_upload_source_read_checksum_and_commit() -> None:
    with minio_storage() as storage, import_api(storage) as fixture:
        job = upload(fixture, [["A", uuid4().hex, "MinIO product", "PA", "UN"]])
        for action in ("validate", "preview", "confirm", "commit"):
            job = command(fixture, job, action)
        assert job["count"] == 1
        assert (
            fixture.client.get(fixture.url, headers=fixture.headers).json()["data"][0]["name"]
            == "MinIO product"
        )


def test_second_product_effect_failure_rolls_back_entire_catalog_and_all_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with import_api() as fixture:
        job = upload(
            fixture,
            [["A", uuid4().hex, "First", "PA", "UN"], ["B", uuid4().hex, "Second", "PA", "UN"]],
        )
        for action in ("validate", "preview", "confirm"):
            job = command(fixture, job, action)
        original = ProductEffects.record
        calls = 0

        async def fail_second(self: ProductEffects, *args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ApplicationError(
                    code="TEST_LATE_FAILURE", message="Injected late fault", status_code=503
                )
            return await original(self, *args, **kwargs)

        monkeypatch.setattr(ProductEffects, "record", fail_second)
        command(fixture, job, "commit", expected_status=503)
        assert fixture.client.get(fixture.url, headers=fixture.headers).json()["data"] == []

        async def verify() -> None:
            async with fixture.data.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEventModel)
                        .where(
                            AuditEventModel.module == "product",
                            AuditEventModel.company_id == fixture.data.company_id,
                        )
                    )
                    == 0
                )

        assert fixture.client.portal is not None
        fixture.client.portal.call(verify)
        monkeypatch.setattr(ProductEffects, "record", original)
        assert command(fixture, job, "commit")["count"] == 2


def test_modified_product_invalidates_confirmation_and_commit_and_revoked_permissions_block_replay() -> (
    None
):
    with import_api() as fixture:
        product = fixture.data.product()

        async def seed() -> None:
            async with fixture.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=product.company_id).add(
                    product, actor_id=fixture.data.actor_id
                )

        assert fixture.client.portal is not None
        fixture.client.portal.call(seed)
        job = upload(fixture, [["", product.sku, "Proposed", "", "CX"]])
        for action in ("validate", "preview"):
            job = command(fixture, job, action)

        async def change() -> None:
            async with fixture.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=product.company_id).save(
                    product.update_details(name="Concurrent", uom="UN"),
                    actor_id=fixture.data.actor_id,
                )

        fixture.client.portal.call(change)
        assert (
            command(fixture, job, "confirm", expected_status=409)["error"]["code"]
            == "IMPORT_PREVIEW_STALE"
        )
        for action in ("validate", "preview", "confirm"):
            job = command(fixture, job, action)
        assert command(fixture, job, "commit")["count"] == 1
        assert fixture.resolver.context is not None
        fixture.resolver.context = replace(
            fixture.resolver.context,
            permissions=fixture.resolver.context.permissions
            - {PermissionCode("product.product.update")},
        )
        command(fixture, job, "commit", expected_status=403)


def test_duplicates_identity_change_and_unchanged_rows() -> None:
    with import_api() as fixture:
        sku = uuid4().hex
        job = upload(fixture, [["A", sku, "A", "PA", "UN"], ["B", sku, "B", "PA", "UN"]])
        rejected = command(fixture, job, "validate")
        assert rejected["error_count"] == 1
        job = upload(fixture, [["C", uuid4().hex, "Create", "PA", "UN"]], key="second")
        for action in ("validate", "preview", "confirm", "commit"):
            job = command(fixture, job, action, key="second")
        created = fixture.client.get(fixture.url, headers=fixture.headers).json()["data"][0]
        unchanged = upload(fixture, [["", created["sku"], "Create", "", "UN"]], key="third")
        for action in ("validate", "preview", "confirm", "commit"):
            unchanged = command(fixture, unchanged, action, key="third")
        assert unchanged["count"] == 0
        bad = upload(fixture, [["OTHER", created["sku"], "Create", "KIT", "UN"]], key="fourth")
        assert (
            "IMMUTABLE_PRODUCT_IDENTITY" in command(fixture, bad, "validate")["rows"][0]["errors"]
        )

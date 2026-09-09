from dataclasses import replace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import update

from erp.modules.governance.infrastructure.import_store import PostgresImportStore
from erp.modules.governance.infrastructure.job_repository import ImportJobRepository
from erp.modules.governance.infrastructure.processing_models import ImportStagingRowModel
from erp.modules.product.contracts import CommandMetadata
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.errors import ApplicationError
from erp.platform.storage.minio import XLSX_CONTENT_TYPE
from tests.integration.import_api_support import (
    MemoryStorage,
    command,
    import_api,
    upload,
    workbook_bytes,
)
from tests.integration.import_support import seed_import

pytestmark = pytest.mark.integration


def test_unsupported_template_and_internal_unknown_command_are_closed() -> None:
    with import_api() as fixture:
        assert fixture.client.portal is not None
        template, _, job = fixture.client.portal.call(seed_import, fixture.data)
        result = fixture.client.post(
            f"/api/v1/data/imports?company_id={fixture.data.company_id}&template_id={template.id}&filename=Import.xlsx",
            headers={
                **fixture.headers,
                "Idempotency-Key": "unsupported",
                "Content-Type": XLSX_CONTENT_TYPE,
            },
            content=workbook_bytes([["A", uuid4().hex, "N", "PA", "UN"]]),
        )
        assert result.status_code == 422
        assert result.json()["error"]["code"] == "IMPORT_TEMPLATE_UNSUPPORTED"
        store = cast(PostgresImportStore, cast(FastAPI, fixture.client.app).state.imports.store)

        async def unsupported() -> None:
            assert fixture.resolver.context is not None
            with pytest.raises(ApplicationError, match="Unsupported"):
                await store.command(
                    fixture.resolver.context,
                    job.company_id,
                    job.id,
                    "unknown",
                    1,
                    "",
                    "",
                    CommandMetadata(uuid4(), uuid4()),
                )

        fixture.client.portal.call(unsupported)


def test_uncertain_upload_outcome_preserves_source_for_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = MemoryStorage()
    with import_api(storage) as fixture:
        monkeypatch.setattr(
            ImportJobRepository, "add", AsyncMock(side_effect=RuntimeError("uncertain DB outcome"))
        )
        with pytest.raises(RuntimeError, match="uncertain DB outcome"):
            upload(fixture, [["A", uuid4().hex, "N", "PA", "UN"]])
        assert len(storage.objects) == 1


def test_api_validation_missing_services_auth_missing_resources_and_preconditions() -> None:
    with import_api() as fixture:
        company = fixture.data.company_id
        job = upload(fixture, [["A", uuid4().hex, "Name", "PA", "UN"]])
        base = f"/api/v1/data/imports/{job['id']}/validate?company_id={company}"
        for value, expected in ((None, 428), ("weak", 400), ('"9999999999"', 400)):
            headers = dict(fixture.headers)
            if value is not None:
                headers["If-Match"] = value
            assert fixture.client.post(base, headers=headers, json={}).status_code == expected
        assert (
            fixture.client.post(
                base.replace("/validate?", "/commit?"),
                headers={**fixture.headers, "If-Match": '"1"'},
                json={},
            ).status_code
            == 400
        )
        assert (
            fixture.client.get(
                f"/api/v1/data/imports/{uuid4()}?company_id={company}", headers=fixture.headers
            ).status_code
            == 404
        )
        missing_job = {**job, "id": str(uuid4())}
        command(fixture, missing_job, "cancel", expected_status=404)
        assert (
            fixture.client.get(
                f"/api/v1/data/import-templates/{uuid4()}/download-model?company_id={company}",
                headers=fixture.headers,
            ).status_code
            == 404
        )
        assert (
            fixture.client.get(
                f"/api/v1/data/imports?company_id={company}",
                headers={"Authorization": "Bearer invalid"},
            ).status_code
            == 401
        )
        app = cast(FastAPI, fixture.client.app)
        service = app.state.imports
        app.state.imports = None
        assert (
            fixture.client.get(
                f"/api/v1/data/imports?company_id={company}", headers=fixture.headers
            ).status_code
            == 503
        )
        app.state.imports = service
        app.state.security_context_resolver = None
        assert (
            fixture.client.get(
                f"/api/v1/data/imports?company_id={company}", headers=fixture.headers
            ).status_code
            == 503
        )


def test_upload_errors_replay_and_storage_not_configured() -> None:
    with import_api() as fixture:
        company = fixture.data.company_id
        template = fixture.client.post(
            f"/api/v1/data/import-templates/product?company_id={company}", headers=fixture.headers
        ).json()["id"]
        assert (
            fixture.client.post(
                f"/api/v1/data/import-templates/product?company_id={company}",
                headers=fixture.headers,
            ).json()["id"]
            == template
        )
        base = (
            f"/api/v1/data/imports?company_id={company}&template_id={template}&filename=Import.xlsx"
        )
        headers = {
            **fixture.headers,
            "Idempotency-Key": "replay",
            "Content-Type": XLSX_CONTENT_TYPE,
        }
        assert fixture.client.post(base, headers=fixture.headers, content=b"x").status_code == 422
        assert (
            fixture.client.post(
                base, headers={**headers, "Content-Type": "text/plain"}, content=b"x"
            ).status_code
            == 415
        )
        assert (
            fixture.client.post(
                base, headers=headers, content=b"x" * (10 * 1024 * 1024 + 1)
            ).status_code
            == 413
        )
        assert fixture.client.post(base, headers=headers, content=b"").status_code == 422
        assert (
            fixture.client.post(
                base + "&commit_mode=VALID_ROWS_ONLY", headers=headers, content=b"x"
            ).status_code
            == 422
        )
        content = workbook_bytes([["A", uuid4().hex, "Name", "PA", "UN"]])
        first = fixture.client.post(base, headers=headers, content=content)
        assert first.status_code == 201
        replay = fixture.client.post(base, headers=headers, content=content)
        assert replay.json()["idempotency_replayed"] is True
        assert replay.json()["id"] == first.json()["id"]
        assert fixture.client.post(base, headers=headers, content=content + b"x").status_code == 409
        app = cast(FastAPI, fixture.client.app)
        app.state.imports.store.storage = None
        assert fixture.client.post(base, headers=headers, content=content).status_code == 503


@pytest.mark.parametrize("staging", [False, True])
def test_source_or_staging_tampering_fails_closed(staging: bool) -> None:
    storage = MemoryStorage()
    with import_api(storage) as fixture:
        job = upload(fixture, [["A", uuid4().hex, "Name", "PA", "UN"]])
        if staging:

            async def tamper() -> None:
                async with fixture.data.database.session() as session, session.begin():
                    await session.execute(
                        update(ImportStagingRowModel)
                        .where(ImportStagingRowModel.company_id == fixture.data.company_id)
                        .values(values={"sku": "tampered"})
                    )

            assert fixture.client.portal is not None
            fixture.client.portal.call(tamper)
        else:
            key = next(iter(storage.objects))
            storage.objects[key] += b"tampered"
        command(fixture, job, "validate", expected_status=409)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_upload_compensates_only_its_own_object(
    monkeypatch: pytest.MonkeyPatch, cleanup_fails: bool
) -> None:
    storage = MemoryStorage()
    with import_api(storage) as fixture:
        monkeypatch.setattr(
            ImportJobRepository,
            "add",
            AsyncMock(
                side_effect=ApplicationError(
                    code="TEST_FAILURE", message="Injected", status_code=503
                )
            ),
        )
        if cleanup_fails:
            monkeypatch.setattr(
                storage, "delete", AsyncMock(side_effect=RuntimeError("injected cleanup failure"))
            )
        template = fixture.client.post(
            f"/api/v1/data/import-templates/product?company_id={fixture.data.company_id}",
            headers=fixture.headers,
        ).json()["id"]
        result = fixture.client.post(
            f"/api/v1/data/imports?company_id={fixture.data.company_id}&template_id={template}&filename=Import.xlsx",
            headers={
                **fixture.headers,
                "Idempotency-Key": "fail",
                "Content-Type": XLSX_CONTENT_TYPE,
            },
            content=workbook_bytes([["A", uuid4().hex, "N", "PA", "UN"]]),
        )
        assert result.status_code == 503
        assert len(storage.objects) == int(cleanup_fails)


def test_global_sku_collision_does_not_expose_foreign_catalog_and_owner_revalidates_missing_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with import_api() as fixture:
        product = fixture.data.product(other_company=True)

        async def seed() -> None:
            async with fixture.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=product.company_id).add(
                    product, actor_id=fixture.data.actor_id
                )

        assert fixture.client.portal is not None
        fixture.client.portal.call(seed)
        job = upload(fixture, [["OWN", product.sku, "Own", "PA", "UN"]])
        result = command(fixture, job, "validate")
        assert result["rows"][0]["errors"] == ["PRODUCT_IDENTIFIER_CONFLICT"]
        assert result["rows"][0]["current"] is None
        own = replace(
            product, company_id=fixture.data.company_id, sku=uuid4().hex.upper(), id=uuid4()
        )

        async def seed_own() -> None:
            async with fixture.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=own.company_id).add(
                    own, actor_id=fixture.data.actor_id
                )

        fixture.client.portal.call(seed_own)
        job = upload(fixture, [["", own.sku, "Updated", "", "CX"]], key="second")
        for action in ("validate", "preview", "confirm"):
            job = command(fixture, job, action)
        monkeypatch.setattr(ProductRepository, "get", AsyncMock(return_value=None))
        command(fixture, job, "commit", expected_status=409)

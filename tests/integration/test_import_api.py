from dataclasses import replace
from io import BytesIO
from typing import Any
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from erp.modules.product.infrastructure import ProductModel, ProductRepository
from erp.platform.audit import AuditEventModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.import_api_support import command, import_api, upload

pytestmark = pytest.mark.integration


def test_full_import_create_update_preview_commit_replay_effects_and_history() -> None:
    with import_api() as fixture:
        existing = fixture.data.product()

        async def seed() -> None:
            async with fixture.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=existing.company_id).add(
                    existing, actor_id=fixture.data.actor_id
                )

        assert fixture.client.portal is not None
        fixture.client.portal.call(seed)
        sku = f"000-{uuid4().hex}"
        job = upload(
            fixture,
            [
                ["", existing.sku, "Updated via import", "", "CX"],
                ["NEW", sku, "New product", "PA", "UN"],
            ],
        )
        company = fixture.data.company_id
        templates = fixture.client.get(
            f"/api/v1/data/import-templates?company_id={company}", headers=fixture.headers
        ).json()
        template_id = templates["items"][0]["id"]
        download = fixture.client.get(
            f"/api/v1/data/import-templates/{template_id}/download-model?company_id={company}",
            headers=fixture.headers,
        )
        assert download.status_code == 200
        workbook = load_workbook(BytesIO(download.content))
        assert workbook["Produtos"]["B2"].number_format == "@"
        workbook.close()
        job = command(fixture, job, "validate")
        assert job["error_count"] == 0
        assert job["rows"][0]["current"]["name"] == existing.name
        assert job["rows"][0]["differences"] == ["name", "uom"]
        job = command(fixture, job, "preview")
        job = command(fixture, job, "confirm")
        committed = command(fixture, job, "commit")
        assert committed["status"] == "COMMITTED"
        assert committed["count"] == 2
        assert command(fixture, job, "commit")["idempotency_replayed"] is True

        async def verify() -> None:
            async with fixture.data.database.session() as session:
                products = list(
                    await session.scalars(
                        select(ProductModel).where(ProductModel.company_id == company)
                    )
                )
                assert len(products) == 2
                assert {product.version for product in products} == {1, 2}
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEventModel)
                        .where(
                            AuditEventModel.module == "product",
                            AuditEventModel.company_id == company,
                        )
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEventModel)
                        .where(
                            OutboxEventModel.source_module == "product",
                            OutboxEventModel.aggregate_id.in_(
                                select(ProductModel.id).where(ProductModel.company_id == company)
                            ),
                        )
                    )
                    == 2
                )

        fixture.client.portal.call(verify)
        history = fixture.client.get(
            f"/api/v1/data/imports?company_id={company}", headers=fixture.headers
        )
        assert history.json()["items"][0]["status"] == "COMMITTED"
        assert (
            fixture.client.get(
                f"/api/v1/data/imports/{job['id']}?company_id={company}", headers=fixture.headers
            ).headers["etag"]
            == '"5"'
        )


@pytest.mark.parametrize(
    "bad",
    [
        ["B", "SKU", "", "PA", "UN"],
        ["B", "SKU", "Name", "INVALID", "UN"],
        ["B", 12345, "Name", "PA", "UN"],
        ["B", "SKU", "Name", "PA", "INVALID UOM"],
    ],
)
def test_one_invalid_row_blocks_every_product_and_generates_rejected_report(bad: list[Any]) -> None:
    with import_api() as fixture:
        job = upload(fixture, [["A", uuid4().hex, "Valid", "PA", "UN"], bad])
        job = command(fixture, job, "validate")
        assert job["status"] == "REJECTED"
        assert job["error_count"] == 1
        assert command(fixture, job, "preview")["status"] == "REJECTED"
        command(fixture, job, "confirm", expected_status=409)
        command(fixture, job, "commit", expected_status=409)
        products = fixture.client.get(fixture.url, headers=fixture.headers).json()
        assert products["data"] == []
        report = fixture.client.get(
            f"/api/v1/data/imports/{job['id']}/rejected-file?company_id={fixture.data.company_id}",
            headers=fixture.headers,
        )
        assert report.status_code == 200
        workbook = load_workbook(BytesIO(report.content))
        assert workbook.active is not None
        assert workbook.active["A2"].value == 3
        workbook.close()


def test_scopes_permissions_stale_job_and_cancel() -> None:
    with import_api() as fixture:
        job = upload(fixture, [["A", uuid4().hex, "Valid", "PA", "UN"]])
        company = fixture.data.company_id
        base = f"/api/v1/data/imports/{job['id']}"
        assert fixture.client.get(f"{base}?company_id={company}").status_code == 401
        assert (
            fixture.client.get(
                f"{base}?company_id={fixture.data.other_company_id}", headers=fixture.headers
            ).status_code
            == 404
        )
        command(fixture, job, "preview", expected_status=409)
        changed = command(fixture, job, "cancel")
        assert changed["status"] == "CANCELLED"
        assert (
            command(fixture, job, "cancel", expected_status=409)["error"]["code"]
            == "VERSION_CONFLICT"
        )
        command(fixture, changed, "validate", expected_status=409)
        assert fixture.resolver.context is not None
        fixture.resolver.context = replace(fixture.resolver.context, permissions=frozenset())
        assert (
            fixture.client.get(f"{base}?company_id={company}", headers=fixture.headers).status_code
            == 403
        )

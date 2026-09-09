"""Company-isolated M23 API fixture; all durable effects cleaned by exact tenant IDs."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from typing import Any, cast

from fastapi import FastAPI
from openpyxl import Workbook
from sqlalchemy import delete

from erp.apps.api.import_composition import compose_imports
from erp.modules.admin.contracts import PermissionCode
from erp.modules.governance.infrastructure.import_models import (
    ImportJobModel,
    ImportTemplateModel,
    ImportTemplateVersionModel,
)
from erp.modules.governance.infrastructure.processing_models import (
    ImportCommitBatchModel,
    ImportStagingRowModel,
    ImportValidationResultModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from erp.platform.storage import ObjectStorage, StoredObject
from erp.platform.storage.minio import XLSX_CONTENT_TYPE
from tests.integration.product_api_support import ApiFixture, product_api


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> StoredObject:
        self.objects[key] = content
        return StoredObject(key, hashlib.sha256(content).hexdigest(), len(content))

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        del self.objects[key]


@contextmanager
def import_api(storage: ObjectStorage | None = None) -> Iterator[ApiFixture]:
    with product_api() as fixture:
        assert fixture.resolver.context is not None
        fixture.resolver.context = replace(
            fixture.resolver.context,
            permissions=frozenset(
                PermissionCode(code)
                for code in (
                    "data.import.execute",
                    "data.import.confirm",
                    "product.product.read",
                    "product.product.create",
                    "product.product.update",
                )
            ),
        )
        cast(FastAPI, fixture.client.app).state.imports = compose_imports(
            fixture.data.database, get_settings(), storage or MemoryStorage()
        )
        try:
            yield fixture
        finally:

            async def cleanup() -> None:
                companies = (fixture.data.company_id, fixture.data.other_company_id)
                async with fixture.data.database.session() as session, session.begin():
                    for model in (
                        ImportCommitBatchModel,
                        ImportValidationResultModel,
                        ImportStagingRowModel,
                        ImportJobModel,
                        ImportTemplateVersionModel,
                        ImportTemplateModel,
                    ):
                        await session.execute(delete(model).where(model.company_id.in_(companies)))
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.module == "governance",
                            AuditEventModel.company_id.in_(companies),
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.source_module == "governance",
                            OutboxEventModel.payload["company_id"].astext.in_(
                                str(company) for company in companies
                            ),
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.in_(
                                f"governance:{company}:{fixture.data.actor_id}"
                                for company in companies
                            )
                        )
                    )

            assert fixture.client.portal is not None
            fixture.client.portal.call(cleanup)


def workbook_bytes(rows: list[list[Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Produtos"
    sheet.append(["code", "sku", "name", "product_type", "uom"])
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def upload(fixture: ApiFixture, rows: list[list[Any]], *, key: str = "upload") -> dict[str, Any]:
    company = fixture.data.company_id
    provision = fixture.client.post(
        f"/api/v1/data/import-templates/product?company_id={company}", headers=fixture.headers
    )
    assert provision.status_code == 201, provision.text
    template = provision.json()["id"]
    result = fixture.client.post(
        f"/api/v1/data/imports?company_id={company}&template_id={template}&filename=Products.xlsx",
        headers={**fixture.headers, "Idempotency-Key": key, "Content-Type": XLSX_CONTENT_TYPE},
        content=workbook_bytes(rows),
    )
    assert result.status_code == 201, result.text
    return dict(result.json())


def command(
    fixture: ApiFixture,
    job: dict[str, Any],
    action: str,
    *,
    expected_status: int = 200,
    key: str = "commit",
) -> dict[str, Any]:
    result = fixture.client.post(
        f"/api/v1/data/imports/{job['id']}/{action}?company_id={fixture.data.company_id}",
        headers={**fixture.headers, "If-Match": f'"{job["version"]}"', "Idempotency-Key": key},
        json={"fingerprint": job.get("fingerprint", "")},
    )
    assert result.status_code == expected_status, result.text
    return dict(result.json())

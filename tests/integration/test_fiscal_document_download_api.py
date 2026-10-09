"""M11 secured PDF/XML downloads backed by tenant-scoped private storage."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.fiscal.application import FISCAL_NFE_ISSUE, FISCAL_NFE_READ
from erp.modules.fiscal.infrastructure import FiscalDocumentRepository
from erp.platform.config import get_settings
from erp.platform.storage import StoredObject
from tests.integration.test_fiscal_document_api import (
    ResolverStub,
    document_body,
)
from tests.integration.test_fiscal_document_repository import fiscal_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key

pytestmark = pytest.mark.integration


class MemoryArtifactStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, content: bytes, *, content_type: str) -> StoredObject:
        self.objects[key] = (content, content_type)
        return StoredObject(key, sha256(content).hexdigest(), len(content))

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def exists(self, key: str) -> bool:
        return key in self.objects


@dataclass(slots=True)
class DownloadApiFixture:
    client: TestClient
    data: ProcurementFixture
    resolver: ResolverStub
    storage: MemoryArtifactStorage

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer fiscal-test-token"}


@contextmanager
def download_api() -> Iterator[DownloadApiFixture]:
    resolver = ResolverStub()
    storage = MemoryArtifactStorage()
    with TestClient(
        create_app(
            get_settings(),
            security_context_resolver=resolver,
            fiscal_artifact_storage=storage,
        )
    ) as client:
        assert client.portal is not None
        manager = fiscal_fixture()
        data, _ = client.portal.call(manager.__aenter__)
        resolver.context = _context(data)
        try:
            yield DownloadApiFixture(client, data, resolver, storage)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def _context(
    data: ProcurementFixture, *, permissions: frozenset[Any] | None = None
) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=permissions or frozenset({FISCAL_NFE_READ, FISCAL_NFE_ISSUE}),
        scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
    )


def _create(api: DownloadApiFixture, *, model: str = "55") -> dict[str, Any]:
    body = document_body(cast(Any, api))
    body["model"] = model
    response = api.client.post("/api/v1/fiscal/documents", json=body, headers=api.headers)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def _authorize(data: ProcurementFixture, document_id: UUID, model: str) -> None:
    async with data.database.session() as session, session.begin():
        repository = FiscalDocumentRepository(session, company_id=data.company_id)
        document = await repository.get(document_id)
        assert document is not None
        issuing = document.start_issuing()
        await repository.save(issuing, actor_id=data.actor_id, expected_version=1)
        key = access_key(model)
        authorized = issuing.authorize(
            access_key=key,
            protocol="135260000000001",
            authorized_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
            authorized_xml=(
                f'<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><infNFe Id="NFe{key}"/></NFe>'
            ),
        )
        await repository.save(authorized, actor_id=data.actor_id, expected_version=2)


def test_danfe_download_is_pdf_stored_under_tenant_date_and_model() -> None:
    with download_api() as api:
        created = _create(api)
        response = api.client.get(
            f"/api/v1/fiscal/documents/{created['id']}/danfe",
            params={"company_id": str(api.data.company_id)},
            headers=api.headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline;")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert len(PdfReader(BytesIO(response.content)).pages) == 1
        key = next(iter(api.storage.objects))
        assert key.startswith(f"fiscal/{api.data.company_id}/")
        assert "/55/" in key
        assert api.storage.objects[key][1] == "application/pdf"
        replay = api.client.get(
            f"/api/v1/fiscal/documents/{created['id']}/danfe",
            params={"company_id": str(api.data.company_id)},
            headers=api.headers,
        )
        assert replay.content == response.content
        assert len(api.storage.objects) == 1


@pytest.mark.parametrize("model", ["55", "65"])
def test_authorized_xml_download_builds_official_distribution_package(model: str) -> None:
    with download_api() as api:
        created = _create(api, model=model)
        assert api.client.portal is not None
        api.client.portal.call(_authorize, api.data, UUID(created["id"]), model)

        response = api.client.get(
            f"/api/v1/fiscal/documents/{created['id']}/xml",
            params={"company_id": str(api.data.company_id)},
            headers=api.headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/xml"
        assert response.headers["content-disposition"].startswith("attachment;")
        root = ET.fromstring(response.content)
        assert root.tag.endswith("nfeProc")
        assert root.findtext(".//{*}cStat") == "100"
        assert any("/2026/10/" in key and f"/{model}/" in key for key in api.storage.objects)


def test_xml_requires_final_document_and_downloads_are_tenant_and_rbac_protected() -> None:
    with download_api() as api:
        created = _create(api)
        url = f"/api/v1/fiscal/documents/{created['id']}/xml"
        draft_xml = api.client.get(
            url,
            params={"company_id": str(api.data.company_id)},
            headers=api.headers,
        )
        assert draft_xml.status_code == 409
        assert draft_xml.json()["error"]["code"] == "FISCAL_DOCUMENT_NOT_EXPORTABLE"

        cross_tenant = api.client.get(
            url,
            params={"company_id": str(api.data.other_company_id)},
            headers=api.headers,
        )
        assert cross_tenant.status_code == 404
        assert cross_tenant.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

        api.resolver.context = _context(api.data, permissions=frozenset({FISCAL_NFE_ISSUE}))
        denied = api.client.get(
            f"/api/v1/fiscal/documents/{created['id']}/danfe",
            params={"company_id": str(api.data.company_id)},
            headers=api.headers,
        )
        assert denied.status_code == 403


def test_download_fails_closed_when_storage_service_is_unavailable() -> None:
    with download_api() as api:
        created = _create(api)
        application = cast(FastAPI, api.client.app)
        application.state.fiscal_document_storage = None
        response = api.client.get(
            f"/api/v1/fiscal/documents/{created['id']}/danfe",
            params={"company_id": str(api.data.company_id)},
            headers=api.headers,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "FISCAL_STORAGE_UNAVAILABLE"

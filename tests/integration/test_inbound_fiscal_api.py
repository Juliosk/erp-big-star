"""Inbound fiscal REST API integration against PostgreSQL and deterministic SEFAZ."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.fiscal.application import (
    FISCAL_INBOUND_MANAGE,
    FISCAL_INBOUND_READ,
    FiscalAuthorization,
    InboundFiscalDocumentService,
)
from erp.modules.fiscal.infrastructure import PostgresInboundFiscalOperations, SefazMockAdapter
from erp.platform.config import get_settings
from tests.integration.test_fiscal_document_api import ResolverStub, _context
from tests.integration.test_inbound_fiscal_repository import inbound_fixture
from tests.unit.modules.fiscal.application.test_inbound_fiscal import inbound_xml

pytestmark = pytest.mark.integration


@contextmanager
def inbound_api() -> Iterator[tuple[TestClient, Any, ResolverStub]]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = inbound_fixture()
        data = client.portal.call(manager.__aenter__)
        application = cast(FastAPI, client.app)
        application.state.inbound_fiscal_documents = InboundFiscalDocumentService(
            PostgresInboundFiscalOperations(data.database, SefazMockAdapter(), ttl_seconds=3600),
            FiscalAuthorization(CompanyAccessService(PostgresCorporateDirectory(data.database))),
        )
        resolver.context = _context(
            data, permissions=frozenset({FISCAL_INBOUND_READ, FISCAL_INBOUND_MANAGE})
        )
        try:
            yield client, data, resolver
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def test_upload_query_manifest_and_idempotent_replay() -> None:
    with inbound_api() as (client, data, _):
        headers = {
            "Authorization": "Bearer fiscal-test-token",
            "Content-Type": "application/xml",
            "Idempotency-Key": "inbound-upload-1",
        }
        url = f"/api/v1/fiscal/inbound-documents/upload?company_id={data.company_id}"
        created = client.post(url, content=inbound_xml(), headers=headers)
        assert created.status_code == 201, created.text
        assert created.headers["etag"] == '"1"'
        assert created.json()["mde_status"] == "PENDING"
        replay = client.post(url, content=inbound_xml(), headers=headers)
        assert replay.headers["idempotency-replayed"] == "true"

        document_id = created.json()["id"]
        detail = client.get(
            f"/api/v1/fiscal/inbound-documents/{document_id}?company_id={data.company_id}",
            headers={"Authorization": "Bearer fiscal-test-token"},
        )
        assert detail.status_code == 200
        manifest = client.post(
            f"/api/v1/fiscal/inbound-documents/{document_id}/manifest?company_id={data.company_id}",
            json={"event_type": "210210"},
            headers={
                "Authorization": "Bearer fiscal-test-token",
                "If-Match": '"1"',
                "Idempotency-Key": "mde-1",
            },
        )
        assert manifest.status_code == 200, manifest.text
        assert manifest.headers["etag"] == '"2"'
        assert manifest.json()["mde_status"] == "ACKNOWLEDGED"


def test_inbound_api_rbac_and_cross_tenant_are_fail_closed() -> None:
    with inbound_api() as (client, data, resolver):
        auth = {"Authorization": "Bearer fiscal-test-token"}
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({FISCAL_INBOUND_READ}),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        denied = client.post(
            f"/api/v1/fiscal/inbound-documents/upload?company_id={data.company_id}",
            content=inbound_xml(),
            headers={**auth, "Content-Type": "application/xml", "Idempotency-Key": "denied"},
        )
        assert denied.status_code == 403
        cross = client.get(
            f"/api/v1/fiscal/inbound-documents/{uuid4()}?company_id={data.other_company_id}",
            headers=auth,
        )
        assert cross.status_code == 404

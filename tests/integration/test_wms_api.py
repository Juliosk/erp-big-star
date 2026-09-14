"""M10 WMS APIs use real PostgreSQL with only identity resolution stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.wms.application.permissions import WMS_PICK_EXECUTE
from erp.modules.wms.infrastructure import (
    PICKING_TASK_SCANNED,
    PICKING_WAVE_RELEASED,
    PackageItemModel,
    PackageModel,
    PickingTaskModel,
    PickingWaveModel,
    ShipmentModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "wms-test-token" else None


@dataclass
class WmsApiFixture:
    client: TestClient
    data: Fixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer wms-test-token"}


@contextmanager
def wms_api() -> Iterator[WmsApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({WMS_PICK_EXECUTE}),
            scopes=frozenset(
                {
                    Scope(ScopeType.COMPANY, data.company_id),
                    Scope(ScopeType.COMPANY, data.other_company_id),
                }
            ),
        )
        try:
            yield WmsApiFixture(client, data, resolver)
        finally:

            async def cleanup_wms() -> None:
                company_ids = (data.company_id, data.other_company_id)
                async with data.database.session() as session, session.begin():
                    await session.execute(
                        delete(OutboxEventModel).where(OutboxEventModel.source_module == "wms")
                    )
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.module == "wms",
                            AuditEventModel.company_id.in_(company_ids),
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.like("wms:%")
                        )
                    )
                    await session.execute(
                        delete(PackageItemModel).where(
                            PackageItemModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(PackageModel).where(PackageModel.company_id.in_(company_ids))
                    )
                    await session.execute(
                        delete(ShipmentModel).where(ShipmentModel.company_id.in_(company_ids))
                    )
                    await session.execute(
                        delete(PickingTaskModel).where(
                            PickingTaskModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(PickingWaveModel).where(
                            PickingWaveModel.company_id.in_(company_ids)
                        )
                    )

            try:
                client.portal.call(cleanup_wms)
            finally:
                client.portal.call(manager.__aexit__, None, None, None)


def _seed_products(api: WmsApiFixture) -> tuple[str, str, str]:
    async def seed() -> tuple[str, str, str]:
        products = (
            api.data.product(code="WMSA"),
            api.data.product(code="WMSB"),
            api.data.product(code="WMSC"),
        )
        async with api.data.database.session() as session, session.begin():
            repository = ProductRepository(session, company_id=api.data.company_id)
            for product in products:
                await repository.add(product, actor_id=api.data.actor_id)
        return (str(products[0].id), str(products[1].id), str(products[2].id))

    assert api.client.portal is not None
    return cast(tuple[str, str, str], api.client.portal.call(seed))


def _seed_product_with_barcode(api: WmsApiFixture, *, barcode: str = "EAN001") -> str:
    async def seed() -> str:
        product = api.data.product(code="WMSBAR")
        async with api.data.database.session() as session, session.begin():
            await ProductRepository(session, company_id=api.data.company_id).add(
                product, actor_id=api.data.actor_id
            )
            session.add(
                ProductBarcodeModel(
                    id=uuid4(),
                    company_id=api.data.company_id,
                    product_id=product.id,
                    barcode_type="EAN",
                    barcode=barcode,
                    created_by=api.data.actor_id,
                    updated_by=api.data.actor_id,
                )
            )
        return str(product.id)

    assert api.client.portal is not None
    return str(api.client.portal.call(seed))


def test_wms_api_creates_lists_and_reads_picking_waves_by_company_scope() -> None:
    with wms_api() as api:
        product_a, product_b, product_c = _seed_products(api)
        created = api.client.post(
            "/api/v1/wms/picking-waves",
            json={
                "company_id": str(api.data.company_id),
                "code": " web-wave ",
                "items": [
                    {"product_id": product_b, "quantity": "2.000000", "zone_code": "B"},
                    {"product_id": product_a, "quantity": "1.000000", "zone_code": "A"},
                    {"product_id": product_c, "quantity": "3.000000", "zone_code": "A"},
                ],
            },
            headers=api.headers,
        )

        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        assert created.headers["cache-control"] == "no-store"
        body = created.json()
        assert body["wave"]["code"] == "WEB-WAVE"
        assert body["wave"]["company_id"] == str(api.data.company_id)
        assert [task["sequence"] for task in body["tasks"]] == [1, 2, 3]
        assert [task["product_id"] for task in body["tasks"]] == [product_a, product_c, product_b]

        waves = api.client.get(
            f"/api/v1/wms/picking-waves?company_id={api.data.company_id}&page_size=1",
            headers=api.headers,
        )
        detail = api.client.get(
            f"/api/v1/wms/picking-waves/{body['wave']['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        foreign = api.client.get(
            f"/api/v1/wms/picking-waves?company_id={api.data.other_company_id}",
            headers=api.headers,
        )

        assert waves.status_code == detail.status_code == foreign.status_code == 200
        assert waves.json()["data"][0]["id"] == body["wave"]["id"]
        assert waves.json()["meta"] == {"page": 1, "page_size": 1, "has_more": False}
        assert detail.headers["etag"] == '"1"'
        assert detail.json()["tasks"][0]["requested_quantity"] == "1.000000"
        assert foreign.json()["data"] == []


def test_wms_api_releases_wave_with_etag_audit_and_outbox() -> None:
    with wms_api() as api:
        product_a, _, _ = _seed_products(api)
        created = api.client.post(
            "/api/v1/wms/picking-waves",
            json={
                "company_id": str(api.data.company_id),
                "code": "RELEASE-ME",
                "items": [{"product_id": product_a, "quantity": "1.000000"}],
            },
            headers=api.headers,
        )
        assert created.status_code == 201
        wave_id = created.json()["wave"]["id"]

        missing_precondition = api.client.post(
            f"/api/v1/wms/picking-waves/{wave_id}/release"
            f"?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert missing_precondition.status_code == 428
        assert missing_precondition.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        released = api.client.post(
            f"/api/v1/wms/picking-waves/{wave_id}/release"
            f"?company_id={api.data.company_id}",
            headers={**api.headers, "If-Match": '"1"'},
        )
        stale = api.client.post(
            f"/api/v1/wms/picking-waves/{wave_id}/release"
            f"?company_id={api.data.company_id}",
            headers={**api.headers, "If-Match": '"1"'},
        )
        detail = api.client.get(
            f"/api/v1/wms/picking-waves/{wave_id}?company_id={api.data.company_id}",
            headers=api.headers,
        )

        assert released.status_code == 200
        assert released.headers["etag"] == '"2"'
        assert released.json()["detail"]["wave"]["status"] == "RELEASED"
        assert released.json()["event_id"] is not None
        assert released.json()["audit_event_id"] is not None
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        assert detail.headers["etag"] == '"2"'
        assert detail.json()["wave"]["status"] == "RELEASED"

        async def verify_effects() -> None:
            async with api.data.database.session() as session:
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(released.json()["event_id"])
                    )
                )
                audit = await session.get(AuditEventModel, UUID(released.json()["audit_event_id"]))
                assert outbox is not None
                assert audit is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert outbox.source_module == "wms"
                assert outbox.event_type == PICKING_WAVE_RELEASED
                assert envelope.message_type == PICKING_WAVE_RELEASED
                assert envelope.aggregate_type == "picking_wave"
                assert envelope.aggregate_version == 2
                assert envelope.company_id == api.data.company_id
                assert envelope.payload["tasks_count"] == 1
                assert audit.module == "wms"
                assert audit.operation == PICKING_WAVE_RELEASED
                assert audit.before_snapshot is not None
                assert audit.before_snapshot["wave"]["status"] == "DRAFT"
                assert audit.after_snapshot is not None
                assert audit.after_snapshot["wave"]["status"] == "RELEASED"

        assert api.client.portal is not None
        api.client.portal.call(verify_effects)


def test_wms_api_scans_picking_task_idempotently_and_blocks_over_pick() -> None:
    with wms_api() as api:
        product_id = _seed_product_with_barcode(api, barcode="EAN001")
        created = api.client.post(
            "/api/v1/wms/picking-waves",
            json={
                "company_id": str(api.data.company_id),
                "code": "SCAN-WAVE",
                "items": [{"product_id": product_id, "quantity": "1.000000"}],
            },
            headers=api.headers,
        )
        assert created.status_code == 201
        wave_id = created.json()["wave"]["id"]
        task_id = created.json()["tasks"][0]["id"]
        assert (
            api.client.post(
                f"/api/v1/wms/picking-waves/{wave_id}/release"
                f"?company_id={api.data.company_id}",
                headers={**api.headers, "If-Match": '"1"'},
            ).status_code
            == 200
        )

        idempotency_key = str(uuid4())
        headers = {**api.headers, "Idempotency-Key": idempotency_key}
        first = api.client.post(
            f"/api/v1/wms/picking-tasks/{task_id}/scan?company_id={api.data.company_id}",
            json={"barcode": "ean001", "quantity": "0.500000"},
            headers=headers,
        )
        replay = api.client.post(
            f"/api/v1/wms/picking-tasks/{task_id}/scan?company_id={api.data.company_id}",
            json={"barcode": "ean001", "quantity": "0.500000"},
            headers=headers,
        )
        completed = api.client.post(
            f"/api/v1/wms/picking-tasks/{task_id}/scan?company_id={api.data.company_id}",
            json={"barcode": "EAN001", "quantity": "0.500000"},
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        over_pick = api.client.post(
            f"/api/v1/wms/picking-tasks/{task_id}/scan?company_id={api.data.company_id}",
            json={"barcode": "EAN001", "quantity": "0.000001"},
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        mismatch = api.client.post(
            f"/api/v1/wms/picking-tasks/{task_id}/scan?company_id={api.data.company_id}",
            json={"barcode": "MISSING", "quantity": "0.000001"},
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )

        assert first.status_code == replay.status_code == 200
        assert first.headers["etag"] == '"2"'
        assert first.headers["idempotency-replayed"] == "false"
        assert replay.headers["idempotency-replayed"] == "true"
        assert first.json()["task"]["picked_quantity"] == "0.500000"
        assert first.json()["task"]["status"] == "IN_PROGRESS"
        assert first.json()["event_id"] == replay.json()["event_id"]
        assert first.json()["audit_event_id"] == replay.json()["audit_event_id"]
        assert completed.status_code == 200
        assert completed.headers["etag"] == '"3"'
        assert completed.json()["task"]["picked_quantity"] == "1.000000"
        assert completed.json()["task"]["status"] == "COMPLETED"
        assert over_pick.status_code == 409
        assert over_pick.json()["error"]["code"] == "WMS_PICKING_TASK_OVER_PICK"
        assert mismatch.status_code == 409
        assert mismatch.json()["error"]["code"] == "WMS_BARCODE_MISMATCH"

        async def verify_scan_effects() -> None:
            async with api.data.database.session() as session:
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(first.json()["event_id"])
                    )
                )
                audit = await session.get(AuditEventModel, UUID(first.json()["audit_event_id"]))
                assert outbox is not None
                assert audit is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert outbox.source_module == "wms"
                assert outbox.event_type == PICKING_TASK_SCANNED
                assert envelope.message_type == PICKING_TASK_SCANNED
                assert envelope.aggregate_type == "picking_task"
                assert envelope.aggregate_version == 2
                assert envelope.payload["barcode"] == "EAN001"
                assert audit.operation == PICKING_TASK_SCANNED
                assert audit.before_snapshot is not None
                assert audit.before_snapshot["picked_quantity"] == "0.000000"
                assert audit.after_snapshot is not None
                assert audit.after_snapshot["picked_quantity"] == "0.500000"

        assert api.client.portal is not None
        api.client.portal.call(verify_scan_effects)


def test_wms_api_enforces_rbac_scope_and_error_contracts() -> None:
    with wms_api() as api:
        assert api.resolver.context is not None
        original = api.resolver.context
        product_id, _, _ = _seed_products(api)

        assert (
            api.client.get(f"/api/v1/wms/picking-waves?company_id={api.data.company_id}")
            .status_code
            == 401
        )
        api.resolver.context = replace(original, permissions=frozenset())
        forbidden = api.client.get(
            f"/api/v1/wms/picking-waves?company_id={api.data.company_id}",
            headers=api.headers,
        )
        api.resolver.context = replace(original, scopes=frozenset())
        scoped = api.client.get(
            f"/api/v1/wms/picking-waves?company_id={api.data.company_id}",
            headers=api.headers,
        )
        api.resolver.context = original
        invalid = api.client.post(
            "/api/v1/wms/picking-waves",
            json={
                "company_id": str(api.data.company_id),
                "code": "bad-zone",
                "items": [
                    {
                        "product_id": product_id,
                        "quantity": "1.000000",
                        "zone_code": "bad zone",
                    }
                ],
            },
            headers=api.headers,
        )
        missing_product = api.client.post(
            "/api/v1/wms/picking-waves",
            json={
                "company_id": str(api.data.company_id),
                "code": "MISSING-PROD",
                "items": [{"product_id": str(uuid4()), "quantity": "1.000000"}],
            },
            headers=api.headers,
        )

        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
        assert scoped.status_code == 403
        assert scoped.json()["error"]["code"] == "SCOPE_FORBIDDEN"
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"
        assert missing_product.status_code == 404
        assert missing_product.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

"""Barcode HTTP slice: company uniqueness, replay, FK and aggregate concurrency."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.product.infrastructure import ProductBarcodeModel, ProductRepository
from erp.platform.audit import AuditEventModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.product_api_support import product_api
from tests.integration.test_product_updates_api import create_for_update

pytestmark = pytest.mark.integration


def test_barcodes_replay_version_uniqueness_and_company_isolation() -> None:
    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        barcode_url = f"{path}/barcodes?{query}"
        body = {"barcode_type": "EAN", "barcode": "4006381333931"}
        headers = {**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())}
        created = api.client.post(barcode_url, json=body, headers=headers)
        assert created.status_code == 201
        assert created.headers["etag"] == '"2"'
        assert (
            api.client.post(barcode_url, json=body, headers=headers).json()["idempotency_replayed"]
            is True
        )
        assert api.client.get(barcode_url, headers=api.headers).json()["data"] == [
            created.json()["barcode"]
        ]
        duplicate = api.client.post(
            barcode_url,
            json=body,
            headers={**headers, "If-Match": '"2"', "Idempotency-Key": str(uuid4())},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "BARCODE_CONFLICT"
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"2"'
        assert (
            api.client.post(
                barcode_url,
                json={**body, "barcode": "96385074"},
                headers={**headers, "Idempotency-Key": str(uuid4())},
            ).json()["error"]["code"]
            == "VERSION_CONFLICT"
        )
        other = api.data.product(other_company=True)

        async def seed() -> None:
            async with api.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=other.company_id).add(
                    other, actor_id=api.data.actor_id
                )

        assert api.client.portal is not None
        api.client.portal.call(seed)
        foreign_url = f"/api/v1/products/{other.id}/barcodes?company_id={other.company_id}"
        assert api.client.get(foreign_url, headers=api.headers).status_code == 404
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            scopes=api.resolver.context.scopes | {Scope(ScopeType.COMPANY, other.company_id)},
        )
        assert api.client.post(foreign_url, json=body, headers=headers).status_code == 201

        async def verify() -> None:
            async with api.data.database.session() as session:
                event = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == created.json()["event_id"]
                    )
                )
                assert event is not None
                assert event.event_type == "ProductBarcodeChanged"
                assert event.payload["payload"]["barcode"] == body["barcode"]
                audit = await session.get(AuditEventModel, created.json()["audit_event_id"])
                assert audit is not None
                assert audit.after_snapshot is not None
                assert audit.after_snapshot["added_barcode"]["barcode"] == body["barcode"]
                session.add(
                    ProductBarcodeModel(
                        id=uuid4(),
                        company_id=api.data.company_id,
                        product_id=other.id,
                        barcode_type="INTERNAL",
                        barcode="FORGED",
                        created_by=api.data.actor_id,
                        updated_by=api.data.actor_id,
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.flush()
                await session.rollback()

        api.client.portal.call(verify)


def test_barcodes_reject_invalid_inputs_and_permissions() -> None:
    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        barcode_url = f"{path}/barcodes?{query}"
        headers = {**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())}
        invalid = api.client.post(
            barcode_url, json={"barcode_type": "EAN", "barcode": "123"}, headers=headers
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "INVALID_BARCODE"
        assert api.resolver.context is not None
        api.resolver.context = replace(api.resolver.context, permissions=frozenset())
        assert api.client.get(barcode_url, headers=api.headers).status_code == 403
        assert (
            api.client.post(
                barcode_url, json={"barcode_type": "INTERNAL", "barcode": "ABC"}, headers=headers
            ).status_code
            == 403
        )

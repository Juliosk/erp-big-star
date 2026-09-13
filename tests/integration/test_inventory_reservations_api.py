"""Inventory reservation APIs: transactional ATP, idempotency and ETags."""

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.inventory.application.permissions import (
    INVENTORY_ADJUSTMENT_CREATE,
    INVENTORY_AVAILABILITY_READ,
    INVENTORY_BALANCE_READ,
    INVENTORY_LOT_CREATE,
    INVENTORY_LOT_READ,
    INVENTORY_RESERVATION_MANAGE,
    INVENTORY_WAREHOUSE_CREATE,
    INVENTORY_WAREHOUSE_READ,
)
from erp.modules.inventory.infrastructure import InventoryReservationModel
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.test_inventory_adjustments_api import (
    _adjustment_body,
    _allow_adjustment,
    _seed_lot_dimensions,
)
from tests.integration.test_inventory_api import InventoryApiFixture, inventory_api

pytestmark = pytest.mark.integration


def _allow_reservation(api: InventoryApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context,
        permissions=frozenset(
            {
                INVENTORY_ADJUSTMENT_CREATE,
                INVENTORY_BALANCE_READ,
                INVENTORY_LOT_CREATE,
                INVENTORY_LOT_READ,
                INVENTORY_WAREHOUSE_CREATE,
                INVENTORY_WAREHOUSE_READ,
                INVENTORY_AVAILABILITY_READ,
                INVENTORY_RESERVATION_MANAGE,
            }
        ),
    )


def _seed_available_stock(
    api: InventoryApiFixture, *, quantity: str = "10"
) -> tuple[str, str, str]:
    _allow_adjustment(api)
    product_id, warehouse_id, lot_id = _seed_lot_dimensions(api)
    body = _adjustment_body(
        api, product_id=product_id, warehouse_id=warehouse_id, quantity=quantity
    )
    body["lines"][0]["lot_id"] = lot_id
    adjustment = api.client.post(
        "/api/v1/inventory/adjustments",
        json=body,
        headers={**api.headers, "Idempotency-Key": str(uuid4())},
    )
    assert adjustment.status_code == 201
    _allow_reservation(api)
    return product_id, warehouse_id, lot_id


def _reservation_body(
    api: InventoryApiFixture,
    *,
    product_id: str,
    warehouse_id: str,
    lot_id: str,
    quantity: str,
    kind: str = "HARD",
) -> dict[str, Any]:
    return {
        "company_id": str(api.data.company_id),
        "reservation_kind": kind,
        "reference_type": "ORDER",
        "reference_id": str(uuid4()),
        "lines": [
            {
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "lot_id": lot_id,
                "state": "AVAILABLE",
                "quantity": quantity,
            }
        ],
    }


def test_hard_reservation_locks_availability_and_replays() -> None:
    with inventory_api() as api:
        product_id, warehouse_id, lot_id = _seed_available_stock(api)
        body = _reservation_body(
            api,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity="6",
        )
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        first = api.client.post("/api/v1/inventory/reservations", json=body, headers=headers)
        replay = api.client.post("/api/v1/inventory/reservations", json=body, headers=headers)

        assert first.status_code == replay.status_code == 201
        assert first.headers["etag"] == '"1"'
        assert first.headers["idempotency-replayed"] == "false"
        assert replay.headers["idempotency-replayed"] == "true"
        assert first.json()["reservation"]["id"] == replay.json()["reservation"]["id"]
        assert first.json()["event_id"] == replay.json()["event_id"]
        assert first.json()["audit_event_id"] == replay.json()["audit_event_id"]

        async def verify_created_event() -> None:
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
                assert envelope.message_type == "InventoryReservationCreated"
                assert envelope.aggregate_type == "inventory_reservation"
                assert envelope.aggregate_id == UUID(first.json()["reservation"]["id"])
                assert envelope.company_id == api.data.company_id
                assert audit.operation == "InventoryReservationCreated"
                assert audit.entity_id == UUID(first.json()["reservation"]["id"])

        assert api.client.portal is not None
        api.client.portal.call(verify_created_event)

        availability = api.client.get(
            f"/api/v1/inventory/availability?company_id={api.data.company_id}"
            f"&product_id={product_id}&warehouse_id={warehouse_id}&lot_id={lot_id}",
            headers=api.headers,
        )
        assert availability.status_code == 200
        item = availability.json()["data"][0]
        assert item["on_hand"] == "10.000000"
        assert item["hard_reserved"] == "6.000000"
        assert item["soft_reserved"] == "0.000000"
        assert item["available"] == "4.000000"

        excessive = _reservation_body(
            api,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity="5",
        )
        conflict = api.client.post(
            "/api/v1/inventory/reservations",
            json=excessive,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "INVENTORY_RESERVATION_CONFLICT"

        soft = _reservation_body(
            api,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity="99",
            kind="SOFT",
        )
        soft_response = api.client.post(
            "/api/v1/inventory/reservations",
            json=soft,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert soft_response.status_code == 201
        refreshed = api.client.get(
            f"/api/v1/inventory/availability?company_id={api.data.company_id}"
            f"&product_id={product_id}&warehouse_id={warehouse_id}&lot_id={lot_id}",
            headers=api.headers,
        ).json()["data"][0]
        assert refreshed["hard_reserved"] == "6.000000"
        assert refreshed["soft_reserved"] == "99.000000"
        assert refreshed["available"] == "4.000000"


def test_release_requires_if_match_updates_etag_and_restores_availability() -> None:
    with inventory_api() as api:
        product_id, warehouse_id, lot_id = _seed_available_stock(api)
        body = _reservation_body(
            api,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity="3",
        )
        created = api.client.post(
            "/api/v1/inventory/reservations",
            json=body,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert created.status_code == 201
        reservation_id = created.json()["reservation"]["id"]

        detail = api.client.get(
            f"/api/v1/inventory/reservations/{reservation_id}"
            f"?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'

        missing_precondition = api.client.post(
            f"/api/v1/inventory/reservations/{reservation_id}/release"
            f"?company_id={api.data.company_id}",
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert missing_precondition.status_code == 428
        assert missing_precondition.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        release_headers = {
            **api.headers,
            "If-Match": '"1"',
            "Idempotency-Key": str(uuid4()),
        }
        released = api.client.post(
            f"/api/v1/inventory/reservations/{reservation_id}/release"
            f"?company_id={api.data.company_id}",
            headers=release_headers,
        )
        replay = api.client.post(
            f"/api/v1/inventory/reservations/{reservation_id}/release"
            f"?company_id={api.data.company_id}",
            headers=release_headers,
        )
        assert released.status_code == replay.status_code == 200
        assert released.headers["etag"] == '"2"'
        assert replay.headers["idempotency-replayed"] == "true"
        assert released.json()["event_id"] == replay.json()["event_id"]
        assert released.json()["audit_event_id"] == replay.json()["audit_event_id"]
        assert released.json()["reservation"]["status"] == "RELEASED"

        async def verify_released_event() -> None:
            async with api.data.database.session() as session:
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(released.json()["event_id"])
                    )
                )
                audit = await session.get(
                    AuditEventModel, UUID(released.json()["audit_event_id"])
                )
                assert outbox is not None
                assert audit is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert envelope.message_type == "InventoryReservationReleased"
                assert envelope.aggregate_version == 2
                assert audit.operation == "InventoryReservationReleased"
                assert audit.before_snapshot is not None
                assert audit.before_snapshot["status"] == "ACTIVE"
                assert audit.after_snapshot is not None
                assert audit.after_snapshot["status"] == "RELEASED"

        assert api.client.portal is not None
        api.client.portal.call(verify_released_event)

        availability = api.client.get(
            f"/api/v1/inventory/availability?company_id={api.data.company_id}"
            f"&product_id={product_id}&warehouse_id={warehouse_id}&lot_id={lot_id}",
            headers=api.headers,
        ).json()["data"][0]
        assert availability["hard_reserved"] == "0.000000"
        assert availability["available"] == "10.000000"

        stale = api.client.post(
            f"/api/v1/inventory/reservations/{reservation_id}/release"
            f"?company_id={api.data.company_id}",
            headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": str(uuid4())},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_reservation_api_enforces_rbac_and_company_scope() -> None:
    with inventory_api() as api:
        product_id, warehouse_id, lot_id = _seed_available_stock(api)
        body = _reservation_body(
            api,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity="1",
        )
        unauthorized = api.client.post(
            "/api/v1/inventory/reservations",
            json=body,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

        assert api.resolver.context is not None
        original = api.resolver.context
        api.resolver.context = replace(original, permissions=frozenset())
        forbidden = api.client.get(
            f"/api/v1/inventory/reservations?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "PERMISSION_FORBIDDEN"

        api.resolver.context = original
        created = api.client.post(
            "/api/v1/inventory/reservations",
            json=body,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert created.status_code == 201
        reservation_id = created.json()["reservation"]["id"]
        scoped = api.client.get(
            f"/api/v1/inventory/reservations/{reservation_id}"
            f"?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert scoped.status_code == 404
        assert scoped.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_reservation_effect_rolls_back_reservation_and_idempotency(
    monkeypatch: pytest.MonkeyPatch, component: type[Any], method: str
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced reservation effect failure")

    with inventory_api() as api:
        product_id, warehouse_id, lot_id = _seed_available_stock(api)
        body = _reservation_body(
            api,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            quantity="1",
        )
        idempotency_key = str(uuid4())
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced reservation effect failure"):
                api.client.post(
                    "/api/v1/inventory/reservations",
                    json=body,
                    headers={**api.headers, "Idempotency-Key": idempotency_key},
                )

        async def counts() -> tuple[int, int, int, int]:
            async with api.data.database.session() as session:
                reservations = await session.scalar(
                    select(func.count())
                    .select_from(InventoryReservationModel)
                    .where(InventoryReservationModel.company_id == api.data.company_id)
                )
                idempotency = await session.scalar(
                    select(func.count())
                    .select_from(IdempotencyRecordModel)
                    .where(
                        IdempotencyRecordModel.scope
                        == f"inventory:{api.data.company_id}:{api.data.actor_id}",
                        IdempotencyRecordModel.idempotency_key == idempotency_key,
                    )
                )
                audit = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.company_id == api.data.company_id,
                        AuditEventModel.operation == "InventoryReservationCreated",
                    )
                )
                outbox = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.source_module == "inventory",
                        OutboxEventModel.event_type == "InventoryReservationCreated",
                    )
                )
                return reservations or 0, idempotency or 0, audit or 0, outbox or 0

        assert api.client.portal is not None
        assert api.client.portal.call(counts) == (0, 0, 0, 0)

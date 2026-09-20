"""Atomic M4-to-M5 reservation, idempotency and over-reservation proofs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.domain import Warehouse
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryReservationAllocationModel,
    InventoryReservationModel,
    WarehouseModel,
    WarehouseRepository,
)
from erp.modules.sales.application import CommandMetadata, ReserveSalesOrder
from erp.modules.sales.infrastructure import (
    PostgresSalesOrderReservations,
    SalesOrderModel,
    SalesOrderReservationLineModel,
    SalesOrderReservationModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_product_persistence import _cnpj
from tests.integration.test_sales_quote_api import SalesApiFixture, sales_api

pytestmark = pytest.mark.integration


def _create_order(api: SalesApiFixture, *, suffix: str, quantity: str) -> tuple[UUID, int]:
    created = api.client.post(
        "/api/v1/sales/quotes",
        headers=api.headers,
        json={
            "company_id": str(api.data.company_id),
            "number": f"Q-RES-{suffix}",
            "customer_id": api.customer_id,
        },
    ).json()
    quote_id = created["id"]
    assert api.client.post(
        f"/api/v1/sales/quotes/{quote_id}/revisions",
        headers={**api.headers, "If-Match": '"1"'},
        json={
            "company_id": str(api.data.company_id),
            "lines": [
                {
                    "product_id": api.product_id,
                    "quantity": quantity,
                    "unit_price": "10.00",
                    "discount_amount": "0.00",
                }
            ],
        },
    ).status_code == 200
    assert api.client.post(
        f"/api/v1/sales/quotes/{quote_id}/send",
        headers={**api.headers, "If-Match": '"2"'},
        json={"company_id": str(api.data.company_id)},
    ).status_code == 200
    assert api.client.post(
        f"/api/v1/sales/quotes/{quote_id}/accept",
        headers={**api.headers, "If-Match": '"3"'},
        json={"company_id": str(api.data.company_id)},
    ).status_code == 200
    converted = api.client.post(
        f"/api/v1/sales/quotes/{quote_id}/convert-to-order",
        headers={
            **api.headers,
            "If-Match": '"4"',
            "Idempotency-Key": f"convert-{suffix}-{uuid4()}",
        },
        json={
            "company_id": str(api.data.company_id),
            "order_number": f"SO-RES-{suffix}",
        },
    )
    assert converted.status_code == 201
    return UUID(converted.json()["order"]["id"]), 2


async def _seed_stock_and_approve(
    api: SalesApiFixture, order_ids: tuple[UUID, ...]
) -> UUID:
    branch = Branch.create(
        company_id=api.data.company_id,
        code=f"R{uuid4().hex[:6]}",
        name="Reservation branch",
        tax_id=_cnpj(),
        timezone="America/Sao_Paulo",
    )
    warehouse = Warehouse.create(
        company_id=api.data.company_id,
        branch_id=branch.id,
        code=f"W{uuid4().hex[:6]}",
        name="Reservation warehouse",
    )
    async with api.data.database.session() as session, session.begin():
        await BranchRepository().add(session, branch, actor_id=api.data.actor_id)
        await WarehouseRepository(session, company_id=api.data.company_id).add(
            warehouse, actor_id=api.data.actor_id
        )
        session.add(
            InventoryBalanceModel(
                id=uuid4(),
                company_id=api.data.company_id,
                product_id=UUID(api.product_id),
                warehouse_id=warehouse.id,
                location_id=None,
                lot_id=None,
                pool_id=None,
                state="AVAILABLE",
                quantity=Decimal("5.000000"),
                version=1,
            )
        )
        await session.execute(
            update(SalesOrderModel)
            .where(
                SalesOrderModel.company_id == api.data.company_id,
                SalesOrderModel.id.in_(order_ids),
            )
            .values(status="APPROVED", version=2, updated_by=api.data.actor_id)
        )
    return warehouse.id


async def _cleanup_reservations(api: SalesApiFixture) -> None:
    company_id = api.data.company_id
    async with api.data.database.session() as session:
        await session.execute(
            delete(SalesOrderReservationLineModel).where(
                SalesOrderReservationLineModel.company_id == company_id
            )
        )
        await session.execute(
            delete(SalesOrderReservationModel).where(
                SalesOrderReservationModel.company_id == company_id
            )
        )
        await session.execute(
            delete(InventoryReservationAllocationModel).where(
                InventoryReservationAllocationModel.company_id == company_id
            )
        )
        await session.execute(
            delete(InventoryReservationModel).where(
                InventoryReservationModel.company_id == company_id
            )
        )
        await session.execute(
            delete(InventoryBalanceModel).where(InventoryBalanceModel.company_id == company_id)
        )
        await session.execute(delete(WarehouseModel).where(WarehouseModel.company_id == company_id))
        await session.execute(delete(BranchModel).where(BranchModel.company_id == company_id))
        await session.execute(
            delete(OutboxEventModel).where(
                OutboxEventModel.payload["company_id"].as_string() == str(company_id)
            )
        )
        await session.execute(
            delete(AuditEventModel).where(AuditEventModel.company_id == company_id)
        )
        await session.commit()
    async with api.data.database.session() as session:
        remaining = await session.scalar(
            select(func.count())
            .select_from(InventoryBalanceModel)
            .where(InventoryBalanceModel.company_id == company_id)
        )
        assert remaining == 0


def test_order_reservation_is_atomic_idempotent_and_prevents_over_reservation() -> None:
    with sales_api() as api:
        assert api.client.portal is not None
        try:
            first_order, expected_version = _create_order(
                api, suffix="A", quantity="3.000000"
            )
            second_order, _ = _create_order(api, suffix="B", quantity="3.000000")
            warehouse_id = api.client.portal.call(
                _seed_stock_and_approve, api, (first_order, second_order)
            )
            adapter = PostgresSalesOrderReservations(api.data.database, ttl_seconds=86_400)
            request_id = uuid4()

            def command(order_id: UUID, key: str) -> ReserveSalesOrder:
                return ReserveSalesOrder(
                    company_id=api.data.company_id,
                    order_id=order_id,
                    warehouse_id=warehouse_id,
                    expected_version=expected_version,
                    idempotency_key=key,
                    metadata=CommandMetadata(request_id, request_id, "127.0.0.1"),
                    expires_at=datetime.now(UTC) + timedelta(hours=2),
                )

            first_command = command(first_order, "reserve-order-A")
            first = api.client.portal.call(adapter.reserve, first_command, api.data.actor_id)
            replay = api.client.portal.call(
                adapter.reserve, first_command, api.data.actor_id
            )
            assert first.reservation.inventory_reservation_id is not None
            assert first.reservation.id == replay.reservation.id
            assert replay.idempotency_replayed is True

            with pytest.raises(ApplicationError) as captured:
                api.client.portal.call(
                    adapter.reserve,
                    command(second_order, "reserve-order-B"),
                    api.data.actor_id,
                )
            assert captured.value.code == "INVENTORY_RESERVATION_CONFLICT"
        finally:
            api.client.portal.call(_cleanup_reservations, api)


def test_order_reservation_post_get_etag_and_tenant_scope() -> None:
    with sales_api() as api:
        assert api.client.portal is not None
        try:
            order_id, expected_version = _create_order(
                api, suffix="API", quantity="2.000000"
            )
            warehouse_id = api.client.portal.call(
                _seed_stock_and_approve, api, (order_id,)
            )
            body = {
                "company_id": str(api.data.company_id),
                "warehouse_id": str(warehouse_id),
                "reservation_kind": "HARD",
                "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            }
            headers = {
                **api.headers,
                "If-Match": f'"{expected_version}"',
                "Idempotency-Key": "sales-order-reservation-api",
            }
            created = api.client.post(
                f"/api/v1/sales/orders/{order_id}/reserve",
                headers=headers,
                json=body,
            )
            assert created.status_code == 201
            assert created.headers["etag"] == '"2"'
            assert created.json()["status"] == "HELD"
            assert created.json()["inventory_event_id"] is not None

            replay = api.client.post(
                f"/api/v1/sales/orders/{order_id}/reserve",
                headers=headers,
                json=body,
            )
            assert replay.status_code == 201
            assert replay.headers["idempotency-replayed"] == "true"

            detail = api.client.get(
                f"/api/v1/sales/orders/{order_id}/reservation"
                f"?company_id={api.data.company_id}",
                headers=api.headers,
            )
            assert detail.status_code == 200
            assert detail.headers["etag"] == '"2"'
            assert detail.json()["order_id"] == str(order_id)

            foreign = api.client.get(
                f"/api/v1/sales/orders/{order_id}/reservation"
                f"?company_id={api.data.other_company_id}",
                headers=api.headers,
            )
            assert foreign.status_code == 404
        finally:
            api.client.portal.call(_cleanup_reservations, api)

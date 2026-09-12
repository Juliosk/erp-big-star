"""Reservation repository and availability query use real PostgreSQL."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import PermissionCode
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.inventory.application import (
    InventoryAuthorization,
    InventoryAvailabilityQueryService,
    InventoryReservationQueryService,
)
from erp.modules.inventory.application.permissions import (
    INVENTORY_AVAILABILITY_READ,
    INVENTORY_RESERVATION_MANAGE,
)
from erp.modules.inventory.domain import (
    InventoryReservation,
    InventoryReservationAllocation,
    InventoryReservationKind,
    InventoryReservationStatus,
    InventoryState,
    Quantity,
)
from erp.modules.inventory.infrastructure import PostgresInventoryReservations
from tests.integration.test_inventory_adjustments_api import (
    _adjustment_body,
    _allow_adjustment,
    _seed_lot_dimensions,
)
from tests.integration.test_inventory_api import InventoryApiFixture, inventory_api

pytestmark = pytest.mark.integration


def _authorization(api: InventoryApiFixture) -> InventoryAuthorization:
    return InventoryAuthorization(CompanyAccessService(PostgresCorporateDirectory(api.data.database)))


def _reservation(
    *,
    company_id: UUID,
    actor_id: UUID,
    product_id: UUID,
    warehouse_id: UUID,
    lot_id: UUID,
    quantity: str,
    kind: InventoryReservationKind,
) -> InventoryReservation:
    return InventoryReservation.create(
        company_id=company_id,
        reservation_kind=kind,
        reference_type="ORDER",
        reference_id=uuid4(),
        created_by=actor_id,
        created_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
        expires_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
        allocations=(
            InventoryReservationAllocation.create(
                reservation_id=uuid4(),
                company_id=company_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                lot_id=lot_id,
                state=InventoryState.AVAILABLE,
                quantity=Quantity.of(quantity),
            ),
        ),
    )


def test_reservation_repository_and_availability_are_company_scoped() -> None:
    with inventory_api() as api:
        _allow_adjustment(api)
        product_id, warehouse_id, lot_id = _seed_lot_dimensions(api)
        body = _adjustment_body(
            api, product_id=product_id, warehouse_id=warehouse_id, quantity="10"
        )
        body["lines"][0]["lot_id"] = lot_id
        adjustment = api.client.post(
            "/api/v1/inventory/adjustments",
            json=body,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert adjustment.status_code == 201

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset(
                {
                    INVENTORY_AVAILABILITY_READ,
                    INVENTORY_RESERVATION_MANAGE,
                    PermissionCode("admin.company.read"),
                }
            ),
        )
        context = api.resolver.context
        assert context is not None
        repository = PostgresInventoryReservations(api.data.database)
        hard = _reservation(
            company_id=api.data.company_id,
            actor_id=api.data.actor_id,
            product_id=UUID(product_id),
            warehouse_id=UUID(warehouse_id),
            lot_id=UUID(lot_id),
            quantity="3",
            kind=InventoryReservationKind.HARD,
        )
        soft = _reservation(
            company_id=api.data.company_id,
            actor_id=api.data.actor_id,
            product_id=UUID(product_id),
            warehouse_id=UUID(warehouse_id),
            lot_id=UUID(lot_id),
            quantity="7",
            kind=InventoryReservationKind.SOFT,
        )

        assert api.client.portal is not None
        api.client.portal.call(repository.add, hard)
        api.client.portal.call(repository.add, soft)

        async def read() -> tuple[Decimal, Decimal, Decimal, str, int]:
            availability = InventoryAvailabilityQueryService(
                repository, _authorization(api)
            )
            reservations = InventoryReservationQueryService(repository, _authorization(api))
            result = await availability.list_availability(
                context,
                api.data.company_id,
                product_id=UUID(product_id),
                warehouse_id=UUID(warehouse_id),
                lot_id=UUID(lot_id),
            )
            active_hard = await reservations.list_reservations(
                context,
                api.data.company_id,
                status=InventoryReservationStatus.ACTIVE,
                reservation_kind=InventoryReservationKind.HARD,
            )
            item = result.items[0]
            return (
                item.hard_reserved.value,
                item.soft_reserved.value,
                item.available.value,
                active_hard.items[0].reference_type,
                len(active_hard.items),
            )

        assert api.client.portal.call(read) == (
            Decimal("3.000000"),
            Decimal("7.000000"),
            Decimal("7.000000"),
            "ORDER",
            1,
        )

        async def hidden_company() -> tuple[int, int]:
            availability = await repository.list_availability(
                api.data.other_company_id,
                product_id=None,
                warehouse_id=None,
                lot_id=None,
                state=None,
                page=1,
                page_size=50,
            )
            reservations = await repository.list_reservations(
                api.data.other_company_id,
                status=None,
                reservation_kind=None,
                page=1,
                page_size=50,
            )
            return len(availability.items), len(reservations.items)

        assert api.client.portal.call(hidden_company) == (0, 0)


def test_reservation_repository_filters_status_and_kind() -> None:
    with inventory_api() as api:
        _allow_adjustment(api)
        product_id, warehouse_id, lot_id = _seed_lot_dimensions(api)
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({INVENTORY_RESERVATION_MANAGE}),
        )
        context = api.resolver.context
        assert context is not None
        active = _reservation(
            company_id=api.data.company_id,
            actor_id=api.data.actor_id,
            product_id=UUID(product_id),
            warehouse_id=UUID(warehouse_id),
            lot_id=UUID(lot_id),
            quantity="1",
            kind=InventoryReservationKind.HARD,
        )
        expired = _reservation(
            company_id=api.data.company_id,
            actor_id=api.data.actor_id,
            product_id=UUID(product_id),
            warehouse_id=UUID(warehouse_id),
            lot_id=UUID(lot_id),
            quantity="1",
            kind=InventoryReservationKind.SOFT,
        ).expire(datetime(2026, 9, 13, 13, tzinfo=UTC) + timedelta(seconds=1))
        repository = PostgresInventoryReservations(api.data.database)
        assert api.client.portal is not None
        api.client.portal.call(repository.add, active)
        api.client.portal.call(repository.add, expired)

        async def read_filtered() -> tuple[int, int, InventoryReservationStatus]:
            service = InventoryReservationQueryService(repository, _authorization(api))
            active_hard = await service.list_reservations(
                context,
                api.data.company_id,
                status=InventoryReservationStatus.ACTIVE,
                reservation_kind=InventoryReservationKind.HARD,
            )
            expired_soft = await service.list_reservations(
                context,
                api.data.company_id,
                status=InventoryReservationStatus.EXPIRED,
                reservation_kind=InventoryReservationKind.SOFT,
            )
            detail = await service.get(context, api.data.company_id, active.id)
            return len(active_hard.items), len(expired_soft.items), detail.status

        assert api.client.portal.call(read_filtered) == (
            1,
            1,
            InventoryReservationStatus.ACTIVE,
        )

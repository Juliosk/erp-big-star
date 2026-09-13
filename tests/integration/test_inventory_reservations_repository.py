"""Reservation repository and availability query use real PostgreSQL."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import PermissionCode
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.inventory.application import (
    InventoryAuthorization,
    InventoryAvailabilityQueryService,
    InventoryReservationQueryService,
)
from erp.modules.inventory.application.commands import (
    CommandMetadata,
    CreateInventoryReservation,
    ExpireInventoryReservations,
    InventoryReservationLine,
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
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel
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


def _reserve_command(
    api: InventoryApiFixture,
    *,
    product_id: UUID,
    warehouse_id: UUID,
    lot_id: UUID,
    quantity: str,
    expires_at: datetime | None = None,
) -> CreateInventoryReservation:
    return CreateInventoryReservation(
        company_id=api.data.company_id,
        reservation_kind=InventoryReservationKind.HARD,
        reference_type="ORDER",
        reference_id=uuid4(),
        lines=(
            InventoryReservationLine(
                product_id=product_id,
                warehouse_id=warehouse_id,
                lot_id=lot_id,
                state=InventoryState.AVAILABLE,
                quantity=Decimal(quantity),
            ),
        ),
        idempotency_key=str(uuid4()),
        metadata=CommandMetadata(
            correlation_id=uuid4(),
            request_id=uuid4(),
        ),
        expires_at=expires_at,
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


def test_hard_reservation_concurrency_prevents_over_reservation() -> None:
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
        repository = PostgresInventoryReservations(api.data.database)

        async def reserve_competing() -> tuple[int, int, Decimal]:
            commands = (
                _reserve_command(
                    api,
                    product_id=UUID(product_id),
                    warehouse_id=UUID(warehouse_id),
                    lot_id=UUID(lot_id),
                    quantity="6",
                ),
                _reserve_command(
                    api,
                    product_id=UUID(product_id),
                    warehouse_id=UUID(warehouse_id),
                    lot_id=UUID(lot_id),
                    quantity="6",
                ),
            )
            results = await asyncio.gather(
                *(repository.reserve(command, api.data.actor_id) for command in commands),
                return_exceptions=True,
            )
            successes = [result for result in results if not isinstance(result, Exception)]
            conflicts = [
                result
                for result in results
                if isinstance(result, ApplicationError)
                and result.code == "INVENTORY_RESERVATION_CONFLICT"
            ]
            availability = await repository.list_availability(
                api.data.company_id,
                product_id=UUID(product_id),
                warehouse_id=UUID(warehouse_id),
                lot_id=UUID(lot_id),
                state=InventoryState.AVAILABLE,
                page=1,
                page_size=50,
            )
            return len(successes), len(conflicts), availability.items[0].available.value

        assert api.client.portal is not None
        assert api.client.portal.call(reserve_competing) == (1, 1, Decimal("4.000000"))


def test_expiration_marks_due_reservations_and_restores_availability() -> None:
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
        repository = PostgresInventoryReservations(api.data.database)
        expires_at = datetime.now(UTC) + timedelta(minutes=5)

        async def expire() -> tuple[str, Decimal, Decimal, int, bool]:
            reserved = await repository.reserve(
                _reserve_command(
                    api,
                    product_id=UUID(product_id),
                    warehouse_id=UUID(warehouse_id),
                    lot_id=UUID(lot_id),
                    quantity="6",
                    expires_at=expires_at,
                ),
                api.data.actor_id,
            )
            before = await repository.list_availability(
                api.data.company_id,
                product_id=UUID(product_id),
                warehouse_id=UUID(warehouse_id),
                lot_id=UUID(lot_id),
                state=InventoryState.AVAILABLE,
                page=1,
                page_size=50,
            )
            expiration_key = str(uuid4())
            expiration = await repository.expire_due(
                ExpireInventoryReservations(
                    company_id=api.data.company_id,
                    now=expires_at + timedelta(minutes=1),
                    batch_size=100,
                    idempotency_key=expiration_key,
                    metadata=CommandMetadata(uuid4(), uuid4()),
                ),
                api.data.actor_id,
            )
            replay = await repository.expire_due(
                ExpireInventoryReservations(
                    company_id=api.data.company_id,
                    now=expires_at + timedelta(minutes=1),
                    batch_size=100,
                    idempotency_key=expiration_key,
                    metadata=CommandMetadata(uuid4(), uuid4()),
                ),
                api.data.actor_id,
            )
            after = await repository.list_availability(
                api.data.company_id,
                product_id=UUID(product_id),
                warehouse_id=UUID(warehouse_id),
                lot_id=UUID(lot_id),
                state=InventoryState.AVAILABLE,
                page=1,
                page_size=50,
            )
            outbox = None
            audit = None
            if expiration.event_ids and expiration.audit_event_ids:
                async with api.data.database.session() as session:
                    outbox = await session.scalar(
                        select(OutboxEventModel).where(
                            OutboxEventModel.event_id == expiration.event_ids[0]
                        )
                    )
                    audit = await session.get(
                        AuditEventModel, expiration.audit_event_ids[0]
                    )
            assert outbox is not None
            assert audit is not None
            envelope = MessageEnvelope.model_validate(outbox.payload)
            assert envelope.message_type == "InventoryReservationExpired"
            assert envelope.aggregate_id == reserved.reservation.id
            assert audit.operation == "InventoryReservationExpired"
            assert audit.before_snapshot is not None
            assert audit.before_snapshot["status"] == "ACTIVE"
            assert audit.after_snapshot is not None
            assert audit.after_snapshot["status"] == "EXPIRED"
            return (
                expiration.expired[0].status.value,
                before.items[0].available.value,
                after.items[0].available.value,
                reserved.reservation.version,
                replay.idempotency_replayed,
            )

        assert api.client.portal is not None
        assert api.client.portal.call(expire) == (
            "EXPIRED",
            Decimal("4.000000"),
            Decimal("10.000000"),
            1,
            True,
        )


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

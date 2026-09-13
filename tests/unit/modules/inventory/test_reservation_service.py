"""Application service rules for inventory reservations."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import CompanyAccessService, SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    PermissionCode,
    Scope,
    ScopeType,
)
from erp.modules.inventory.application.commands import (
    CommandMetadata,
    CreateInventoryReservation,
    ExpireInventoryReservations,
    InventoryReservationExpirationResult,
    InventoryReservationLine,
    InventoryReservationResult,
    ReleaseInventoryReservation,
)
from erp.modules.inventory.application.permissions import (
    INVENTORY_RESERVATION_MANAGE,
    InventoryAuthorization,
)
from erp.modules.inventory.application.reservations import (
    InventoryReservationService,
    InventoryReservationStore,
)
from erp.modules.inventory.domain import (
    InventoryReservation,
    InventoryReservationAllocation,
    InventoryReservationKind,
    Quantity,
)
from erp.platform.errors import ApplicationError
from tests.unit.modules.inventory.test_permissions import CompanyAccessStub


class ReservationStoreStub:
    def __init__(self) -> None:
        self.reserved: list[CreateInventoryReservation] = []
        self.released: list[ReleaseInventoryReservation] = []
        self.expired: list[ExpireInventoryReservations] = []

    async def reserve(
        self, command: CreateInventoryReservation, actor_id: UUID
    ) -> InventoryReservationResult:
        self.reserved.append(command)
        reservation = InventoryReservation.create(
            company_id=command.company_id,
            reservation_kind=command.reservation_kind,
            reference_type=command.reference_type,
            reference_id=command.reference_id,
            created_by=actor_id,
            allocations=(
                InventoryReservationAllocation.create(
                    reservation_id=uuid4(),
                    company_id=command.company_id,
                    product_id=command.lines[0].product_id,
                    warehouse_id=command.lines[0].warehouse_id,
                    quantity=Quantity(command.lines[0].quantity),
                ),
            ),
        )
        return InventoryReservationResult(reservation)

    async def release(
        self, command: ReleaseInventoryReservation, actor_id: UUID
    ) -> InventoryReservationResult:
        self.released.append(command)
        reservation = InventoryReservation.create(
            company_id=command.company_id,
            reservation_kind=InventoryReservationKind.HARD,
            reference_type="ORDER",
            reference_id=uuid4(),
            created_by=actor_id,
            allocations=(
                InventoryReservationAllocation.create(
                    reservation_id=command.reservation_id,
                    company_id=command.company_id,
                    product_id=uuid4(),
                    warehouse_id=uuid4(),
                    quantity=Quantity.of("1"),
                ),
            ),
        ).release()
        return InventoryReservationResult(reservation)

    async def expire_due(
        self, command: ExpireInventoryReservations, actor_id: UUID
    ) -> InventoryReservationExpirationResult:
        self.expired.append(command)
        reservation = InventoryReservation.create(
            company_id=command.company_id,
            reservation_kind=InventoryReservationKind.HARD,
            reference_type="ORDER",
            reference_id=uuid4(),
            created_by=actor_id,
            allocations=(
                InventoryReservationAllocation.create(
                    reservation_id=uuid4(),
                    company_id=command.company_id,
                    product_id=uuid4(),
                    warehouse_id=uuid4(),
                    quantity=Quantity.of("1"),
                ),
            ),
        )
        return InventoryReservationExpirationResult((reservation.expire(command.now),))


def _context(company_id: UUID, *, permissions: frozenset[PermissionCode]) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=permissions,
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _command(company_id: UUID, *, quantity: str = "1") -> CreateInventoryReservation:
    return CreateInventoryReservation(
        company_id=company_id,
        reservation_kind=InventoryReservationKind.HARD,
        reference_type="ORDER",
        reference_id=uuid4(),
        lines=(
            InventoryReservationLine(
                product_id=uuid4(),
                warehouse_id=uuid4(),
                quantity=Decimal(quantity),
            ),
        ),
        idempotency_key="reservation-test",
        metadata=CommandMetadata(uuid4(), uuid4()),
    )


def _authorization(companies: CompanyAccessStub) -> InventoryAuthorization:
    return InventoryAuthorization(cast(CompanyAccessService, companies))


def test_reservation_service_authorizes_company_and_permission_before_reserving() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        companies = CompanyAccessStub()
        store = ReservationStoreStub()
        service = InventoryReservationService(
            cast(InventoryReservationStore, store), _authorization(companies)
        )
        context = _context(company_id, permissions=frozenset({INVENTORY_RESERVATION_MANAGE}))
        result = await service.reserve(context, _command(company_id))

        assert result.reservation.company_id == company_id
        assert len(store.reserved) == 1
        assert companies.calls == [(company_id, True)]

    asyncio.run(scenario())


def test_reservation_service_rejects_missing_permission_and_invalid_quantity() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        service = InventoryReservationService(
            cast(InventoryReservationStore, ReservationStoreStub()),
            _authorization(CompanyAccessStub()),
        )
        with pytest.raises(ApplicationError) as forbidden:
            await service.reserve(_context(company_id, permissions=frozenset()), _command(company_id))
        with pytest.raises(ApplicationError) as invalid:
            await service.reserve(
                _context(company_id, permissions=frozenset({INVENTORY_RESERVATION_MANAGE})),
                _command(company_id, quantity="0"),
            )

        assert forbidden.value.code == "PERMISSION_FORBIDDEN"
        assert invalid.value.code == "BUSINESS_VALIDATION_ERROR"

    asyncio.run(scenario())


def test_reservation_service_release_requires_positive_version() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        store = ReservationStoreStub()
        service = InventoryReservationService(
            cast(InventoryReservationStore, store), _authorization(CompanyAccessStub())
        )
        context = _context(company_id, permissions=frozenset({INVENTORY_RESERVATION_MANAGE}))
        command = ReleaseInventoryReservation(
            company_id=company_id,
            reservation_id=uuid4(),
            expected_version=0,
            idempotency_key="release",
            metadata=CommandMetadata(uuid4(), uuid4()),
        )
        with pytest.raises(ApplicationError) as invalid:
            await service.release(context, command)
        result = await service.release(context, replace(command, expected_version=1))

        assert invalid.value.code == "BUSINESS_VALIDATION_ERROR"
        assert result.reservation.version == 2
        assert len(store.released) == 1

    asyncio.run(scenario())


def test_reservation_service_expiration_requires_aware_now_and_batch_limits() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        store = ReservationStoreStub()
        service = InventoryReservationService(
            cast(InventoryReservationStore, store), _authorization(CompanyAccessStub())
        )
        context = _context(company_id, permissions=frozenset({INVENTORY_RESERVATION_MANAGE}))
        command = ExpireInventoryReservations(
            company_id=company_id,
            now=datetime.fromisoformat("2026-09-13T09:00:00"),
            batch_size=100,
            idempotency_key="expire",
            metadata=CommandMetadata(uuid4(), uuid4()),
        )
        with pytest.raises(ApplicationError) as invalid_time:
            await service.expire_due(context, command)
        with pytest.raises(ApplicationError) as invalid_batch:
            await service.expire_due(
                context,
                replace(
                    command,
                    now=datetime.now(UTC),
                    batch_size=0,
                ),
            )
        result = await service.expire_due(
            context,
            replace(
                command,
                now=datetime.now(UTC),
                batch_size=1,
            ),
        )

        assert invalid_time.value.code == "BUSINESS_VALIDATION_ERROR"
        assert invalid_batch.value.code == "BUSINESS_VALIDATION_ERROR"
        assert result.expired[0].status.value == "EXPIRED"
        assert len(store.expired) == 1

    asyncio.run(scenario())

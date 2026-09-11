"""Pure application coverage for inventory adjustment commands."""

import asyncio
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.inventory.application.adjustments import (
    InventoryAdjustmentService,
    InventoryAdjustmentStore,
    build_adjustment_entry,
)
from erp.modules.inventory.application.commands import (
    CommandMetadata,
    CreateInventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentResult,
    InventoryAdjustmentType,
)
from erp.modules.inventory.application.permissions import (
    INVENTORY_ADJUSTMENT_CREATE,
    InventoryAuthorization,
)
from erp.modules.inventory.domain import InventoryBalance, Quantity
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, object, bool]] = []

    async def require(
        self, context: SecurityContext, company_id: UUID, permission: object, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeStore:
    def __init__(self) -> None:
        self.command: CreateInventoryAdjustment | None = None
        self.actor_id: UUID | None = None

    async def adjust(
        self, command: CreateInventoryAdjustment, actor_id: UUID
    ) -> InventoryAdjustmentResult:
        self.command = command
        self.actor_id = actor_id
        entry = build_adjustment_entry(command, actor_id=actor_id)
        balance = InventoryBalance.from_posting(entry.postings[0])
        return InventoryAdjustmentResult(entry.transaction.id, (balance,), uuid4(), uuid4())


def _context(user_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(user_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(),
        scopes=frozenset(),
    )


def _command(
    adjustment_type: InventoryAdjustmentType = InventoryAdjustmentType.INBOUND,
    *,
    quantity: str = "5",
) -> CreateInventoryAdjustment:
    return CreateInventoryAdjustment(
        company_id=uuid4(),
        adjustment_type=adjustment_type,
        reason="Inventory correction",
        lines=(
            InventoryAdjustmentLine(
                product_id=uuid4(),
                warehouse_id=uuid4(),
                quantity=Decimal(quantity),
            ),
        ),
        idempotency_key=str(uuid4()),
        metadata=CommandMetadata(request_id=uuid4(), correlation_id=uuid4()),
    )


def test_build_adjustment_entry_signs_quantities_and_reference_type() -> None:
    actor_id = uuid4()

    inbound = build_adjustment_entry(_command(), actor_id=actor_id)
    outbound = build_adjustment_entry(
        _command(InventoryAdjustmentType.OUTBOUND, quantity="2"), actor_id=actor_id
    )
    balance = build_adjustment_entry(
        _command(InventoryAdjustmentType.BALANCE, quantity="12"),
        actor_id=actor_id,
        current_quantities=(Decimal("7"),),
    )

    assert inbound.transaction.reference_type == "INBOUND_ADJUSTMENT"
    assert inbound.postings[0].quantity_delta == Decimal("5")
    assert outbound.transaction.reference_type == "OUTBOUND_ADJUSTMENT"
    assert outbound.postings[0].quantity_delta == Decimal("-2")
    assert balance.transaction.reference_type == "BALANCE_ADJUSTMENT"
    assert balance.postings[0].quantity_delta == Decimal("5")


def test_adjustment_service_authorizes_before_store_call() -> None:
    async def scenario() -> None:
        actor_id = uuid4()
        command = _command()
        authorization = FakeAuthorization()
        store = FakeStore()
        service = InventoryAdjustmentService(
            cast(InventoryAdjustmentStore, store),
            cast(InventoryAuthorization, authorization),
        )

        result = await service.adjust(_context(actor_id), command)

        assert result.balances[0].quantity == Quantity.of("5")
        assert store.command == command
        assert store.actor_id == actor_id
        assert authorization.calls == [
            (command.company_id, INVENTORY_ADJUSTMENT_CREATE, True),
        ]

    asyncio.run(scenario())


def test_adjustment_service_rejects_invalid_or_noop_business_rules() -> None:
    async def scenario() -> None:
        service = InventoryAdjustmentService(
            cast(InventoryAdjustmentStore, FakeStore()),
            cast(InventoryAuthorization, FakeAuthorization()),
        )

        with pytest.raises(ApplicationError) as captured:
            await service.adjust(_context(uuid4()), _command(quantity="0"))
        assert captured.value.code == "BUSINESS_VALIDATION_ERROR"

        with pytest.raises(ValueError, match="does not change"):
            build_adjustment_entry(
                _command(InventoryAdjustmentType.BALANCE, quantity="7"),
                actor_id=uuid4(),
                current_quantities=(Decimal("7"),),
            )

    asyncio.run(scenario())

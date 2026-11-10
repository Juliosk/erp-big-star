"""Commit 212: atomic WMS putaway, M5 ledger and tenant concurrency proofs."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text

from erp.modules.admin.contracts import CompanyAccessService, SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryPostingModel,
    InventoryTransactionModel,
)
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.wms.application import (
    WMS_INVENTORY_MOVEMENT,
    CommandMetadata,
    ExecutePutaway,
    PutawaySourceType,
    WmsAuthorization,
    WmsPutawayResult,
    WMSPutawayService,
)
from erp.modules.wms.domain import (
    BinCapacity,
    BinDimensions,
    StockCondition,
    StorageType,
    WarehouseBin,
)
from erp.modules.wms.infrastructure import (
    WMS_PUTAWAY_COMPLETED,
    PostgresWmsPutawayStore,
    WMSLocationRepository,
)
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_wms_location_repository import (
    WmsLocationFixture,
    _bin,
    wms_location_fixture,
)

pytestmark = pytest.mark.integration
D = Decimal
DEFAULT_QUANTITY = D("2.000000")


class CompanyAccessStub:
    async def require_company(
        self, context: SecurityContext, company_id: UUID, *, write: bool = False
    ) -> None:
        assert company_id in {scope.scope_id for scope in context.scopes}
        assert write


@dataclass(frozen=True, slots=True)
class PutawayFixture:
    locations: WmsLocationFixture
    product_id: UUID
    target: WarehouseBin
    context: SecurityContext


@asynccontextmanager
async def putaway_fixture(
    *, capacity_units: int = 10, target_zone: str = "PICK"
) -> AsyncIterator[PutawayFixture]:
    async with wms_location_fixture() as locations:
        product = locations.data.product(code="PUTAWAY")
        target = _bin(
            locations,
            locations.locations[0],
            zone=target_zone,
            storage_type=StorageType.PICKING,
        )
        target = replace(
            target,
            capacity=BinCapacity(
                dimensions=BinDimensions(D("2"), D("2"), D("2")),
                max_weight=D("100"),
                max_units=capacity_units,
            ),
        )
        async with locations.database.session() as session, session.begin():
            await ProductRepository(session, company_id=locations.company_id).add(
                product, actor_id=locations.actor_id
            )
            await WMSLocationRepository(
                session, company_id=locations.company_id
            ).add(target, actor_id=locations.actor_id)
            session.add(
                InventoryBalanceModel(
                    id=uuid4(),
                    company_id=locations.company_id,
                    product_id=product.id,
                    warehouse_id=locations.warehouse.id,
                    location_id=locations.locations[1].id,
                    lot_id=None,
                    pool_id=None,
                    state="RECEIVING_STAGE",
                    quantity=D("10.000000"),
                    version=1,
                )
            )
        context = _context(locations, locations.company_id)
        try:
            yield PutawayFixture(locations, product.id, target, context)
        finally:
            async with locations.database.session() as session, session.begin():
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.scope.like(
                            f"wms:{locations.company_id}:%"
                        )
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.payload["company_id"].as_string()
                        == str(locations.company_id)
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(
                        AuditEventModel.company_id == locations.company_id
                    )
                )
                await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
                await session.execute(
                    delete(InventoryPostingModel).where(
                        InventoryPostingModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(InventoryTransactionModel).where(
                        InventoryTransactionModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == locations.company_id
                    )
                )


def _context(locations: WmsLocationFixture, company_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(
            locations.actor_id, uuid4(), AuthenticationLevel.LEVEL_2
        ),
        permissions=frozenset({WMS_INVENTORY_MOVEMENT}),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _service(data: PutawayFixture) -> WMSPutawayService:
    authorization = WmsAuthorization(
        cast(CompanyAccessService, CompanyAccessStub())
    )
    return WMSPutawayService(
        PostgresWmsPutawayStore(data.locations.database), authorization
    )


def _command(
    data: PutawayFixture,
    *,
    company_id: UUID | None = None,
    expected_version: int = 1,
    idempotency_key: str = "putaway-212",
    quantity: Decimal = DEFAULT_QUANTITY,
    units: int = 2,
    allowed_zones: tuple[str, ...] = ("PICK",),
) -> ExecutePutaway:
    locations = data.locations
    return ExecutePutaway(
        company_id=company_id or locations.company_id,
        warehouse_id=locations.warehouse.id,
        product_id=data.product_id,
        source_location_id=locations.locations[1].id,
        target_bin_id=data.target.inventory_location_id,
        source_type=PutawaySourceType.PURCHASE_RECEIPT,
        source_id=uuid4(),
        quantity=quantity,
        units=units,
        unit_weight=D("2"),
        dimensions=BinDimensions(D("1"), D("1"), D("1")),
        condition=StockCondition.AVAILABLE,
        allowed_zones=allowed_zones,
        expected_bin_version=expected_version,
        idempotency_key=idempotency_key,
        metadata=CommandMetadata(uuid4(), uuid4(), "127.0.0.1"),
    )


def test_putaway_is_atomic_and_idempotent_across_wms_m5_audit_and_outbox() -> None:
    async def scenario() -> None:
        async with putaway_fixture() as data:
            service = _service(data)
            command = _command(data)
            result = await service.putaway(data.context, command)
            replay = await service.putaway(data.context, command)

            assert result.target_bin.version == 2
            assert result.target_bin.occupied_units == 2
            assert result.target_bin.used_weight == D("4")
            assert result.target_bin.used_volume == D("2")
            assert result.source_balance.on_hand == D("8.000000")
            assert result.source_balance.state == "RECEIVING_STAGE"
            assert result.destination_balance.on_hand == D("2.000000")
            assert result.destination_balance.state == "AVAILABLE"
            assert replay == replace(result, idempotency_replayed=True)

            async with data.locations.database.session() as session:
                postings = tuple(
                    await session.scalars(
                        select(InventoryPostingModel)
                        .where(
                            InventoryPostingModel.company_id
                            == data.locations.company_id,
                            InventoryPostingModel.transaction_id
                            == result.transaction_id,
                        )
                        .order_by(InventoryPostingModel.sequence)
                    )
                )
                assert [posting.quantity_delta for posting in postings] == [
                    D("-2.000000"),
                    D("2.000000"),
                ]
                assert [posting.location_id for posting in postings] == [
                    data.locations.locations[1].id,
                    data.target.inventory_location_id,
                ]
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InventoryTransactionModel)
                        .where(
                            InventoryTransactionModel.company_id
                            == data.locations.company_id
                        )
                    )
                    == 1
                )
                event = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == result.event_id
                    )
                )
                audit = await session.get(AuditEventModel, result.audit_event_id)
                assert event is not None
                assert event.event_type == WMS_PUTAWAY_COMPLETED
                assert event.aggregate_id == result.transaction_id
                assert audit is not None
                assert audit.operation == WMS_PUTAWAY_COMPLETED
                assert audit.before_snapshot is not None
                assert audit.after_snapshot is not None

    asyncio.run(scenario())


def test_inventory_failure_rolls_back_ledger_bin_audit_and_outbox() -> None:
    async def scenario() -> None:
        async with putaway_fixture() as data:
            with pytest.raises(ApplicationError) as captured:
                await _service(data).putaway(
                    data.context,
                    _command(data, quantity=D("11.000000"), units=1),
                )
            assert captured.value.code == "INVENTORY_NEGATIVE_BALANCE"
            async with data.locations.database.session() as session:
                target = await WMSLocationRepository(
                    session, company_id=data.locations.company_id
                ).get(data.target.inventory_location_id)
                transaction_count = await session.scalar(
                    select(func.count())
                    .select_from(InventoryTransactionModel)
                    .where(
                        InventoryTransactionModel.company_id
                        == data.locations.company_id
                    )
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.payload["company_id"].as_string()
                        == str(data.locations.company_id)
                    )
                )
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(AuditEventModel.company_id == data.locations.company_id)
                )
                assert target == data.target
                assert transaction_count == 0
                assert event_count == 0
                assert audit_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("capacity_units", "units", "allowed_zones", "expected_code"),
    [
        (1, 2, ("PICK",), "BIN_CAPACITY_EXCEEDED"),
        (10, 2, ("RESERVE",), "PUTAWAY_ZONE_FORBIDDEN"),
    ],
)
def test_full_or_incompatible_bin_rolls_back_every_effect(
    capacity_units: int,
    units: int,
    allowed_zones: tuple[str, ...],
    expected_code: str,
) -> None:
    async def scenario() -> None:
        async with putaway_fixture(capacity_units=capacity_units) as data:
            with pytest.raises(ApplicationError) as captured:
                await _service(data).putaway(
                    data.context,
                    _command(data, units=units, allowed_zones=allowed_zones),
                )
            assert captured.value.code == expected_code
            async with data.locations.database.session() as session:
                source = await session.scalar(
                    select(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == data.locations.company_id,
                        InventoryBalanceModel.location_id
                        == data.locations.locations[1].id,
                    )
                )
                stored_bin = await WMSLocationRepository(
                    session, company_id=data.locations.company_id
                ).get(data.target.inventory_location_id)
                transaction_count = await session.scalar(
                    select(func.count())
                    .select_from(InventoryTransactionModel)
                    .where(
                        InventoryTransactionModel.company_id
                        == data.locations.company_id
                    )
                )
                assert source is not None
                assert source.quantity == D("10.000000")
                assert stored_bin == data.target
                assert transaction_count == 0

    asyncio.run(scenario())


def test_putaway_hides_a_known_bin_from_another_company() -> None:
    async def scenario() -> None:
        async with putaway_fixture() as data:
            foreign_context = _context(data.locations, data.locations.other_company_id)
            with pytest.raises(ApplicationError) as captured:
                await _service(data).putaway(
                    foreign_context,
                    _command(data, company_id=data.locations.other_company_id),
                )
            assert captured.value.code == "RESOURCE_NOT_FOUND"
            async with data.locations.database.session() as session:
                target = await WMSLocationRepository(
                    session, company_id=data.locations.company_id
                ).get(data.target.inventory_location_id)
                assert target == data.target

    asyncio.run(scenario())


def test_concurrent_putaway_has_one_optimistic_version_winner() -> None:
    async def scenario() -> None:
        async with putaway_fixture() as data:
            service = _service(data)
            outcomes = await asyncio.gather(
                service.putaway(
                    data.context,
                    _command(data, idempotency_key="putaway-race-a", units=1),
                ),
                service.putaway(
                    data.context,
                    _command(data, idempotency_key="putaway-race-b", units=1),
                ),
                return_exceptions=True,
            )
            winners = [value for value in outcomes if isinstance(value, WmsPutawayResult)]
            conflicts = [
                value
                for value in outcomes
                if isinstance(value, ApplicationError)
                and value.code == "VERSION_CONFLICT"
            ]
            assert len(winners) == 1
            assert len(conflicts) == 1
            async with data.locations.database.session() as session:
                target = await WMSLocationRepository(
                    session, company_id=data.locations.company_id
                ).get(data.target.inventory_location_id)
                assert target is not None
                assert target.version == 2
                assert target.occupied_units == 1
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InventoryTransactionModel)
                        .where(
                            InventoryTransactionModel.company_id
                            == data.locations.company_id
                        )
                    )
                    == 1
                )

    asyncio.run(scenario())


__all__: list[str] = []

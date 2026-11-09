"""PostgreSQL coverage for the tenant-bound WMS physical hierarchy."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.domain import Warehouse, WarehouseLocation
from erp.modules.inventory.infrastructure import (
    WarehouseLocationModel,
    WarehouseLocationRepository,
    WarehouseModel,
    WarehouseRepository,
)
from erp.modules.wms.domain import (
    BinCapacity,
    BinDimensions,
    OccupancyStatus,
    PutawayLoad,
    PutawayPolicy,
    StockCondition,
    StorageType,
    WarehouseAddress,
    WarehouseBin,
)
from erp.modules.wms.infrastructure import (
    WmsAisleModel,
    WmsBayModel,
    WmsBinCapacityModel,
    WmsBinModel,
    WmsLevelModel,
    WMSLocationRepository,
    WmsZoneModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, _cnpj, fixture

pytestmark = pytest.mark.integration
D = Decimal
ZERO = D("0")


@dataclass(frozen=True)
class WmsLocationFixture:
    data: Fixture
    warehouse: Warehouse
    foreign_warehouse: Warehouse
    locations: tuple[WarehouseLocation, ...]
    foreign_location: WarehouseLocation

    @property
    def company_id(self) -> UUID:
        return self.data.company_id

    @property
    def other_company_id(self) -> UUID:
        return self.data.other_company_id

    @property
    def actor_id(self) -> UUID:
        return self.data.actor_id

    @property
    def database(self) -> Database:
        return self.data.database


@asynccontextmanager
async def wms_location_fixture() -> AsyncIterator[WmsLocationFixture]:
    async with fixture() as data:
        own_branch = Branch.create(
            company_id=data.company_id,
            code=f"W{uuid4().hex[:8].upper()}",
            name="WMS branch",
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        foreign_branch = Branch.create(
            company_id=data.other_company_id,
            code=f"W{uuid4().hex[:8].upper()}",
            name="Foreign WMS branch",
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        warehouse = Warehouse.create(
            company_id=data.company_id,
            branch_id=own_branch.id,
            code=f"W{uuid4().hex[:8].upper()}",
            name="Main WMS warehouse",
        )
        foreign_warehouse = Warehouse.create(
            company_id=data.other_company_id,
            branch_id=foreign_branch.id,
            code=f"W{uuid4().hex[:8].upper()}",
            name="Foreign WMS warehouse",
        )
        locations = tuple(
            WarehouseLocation.create(
                company_id=data.company_id,
                warehouse_id=warehouse.id,
                code=f"BIN{sequence:02d}",
                name=f"WMS bin {sequence}",
            )
            for sequence in range(1, 6)
        )
        foreign_location = WarehouseLocation.create(
            company_id=data.other_company_id,
            warehouse_id=foreign_warehouse.id,
            code="BIN01",
            name="Foreign WMS bin",
        )
        async with data.database.session() as session, session.begin():
            branches = BranchRepository()
            await branches.add(session, own_branch, actor_id=data.actor_id)
            await branches.add(session, foreign_branch, actor_id=data.actor_id)
            await WarehouseRepository(session, company_id=data.company_id).add(
                warehouse, actor_id=data.actor_id
            )
            await WarehouseRepository(session, company_id=data.other_company_id).add(
                foreign_warehouse, actor_id=data.actor_id
            )
            own_locations = WarehouseLocationRepository(
                session, company_id=data.company_id
            )
            for location in locations:
                await own_locations.add(location, actor_id=data.actor_id)
            await WarehouseLocationRepository(
                session, company_id=data.other_company_id
            ).add(foreign_location, actor_id=data.actor_id)
        resources = WmsLocationFixture(
            data,
            warehouse,
            foreign_warehouse,
            locations,
            foreign_location,
        )
        company_ids = (data.company_id, data.other_company_id)
        try:
            yield resources
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(WmsBinCapacityModel).where(
                        WmsBinCapacityModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(WmsBinModel).where(WmsBinModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(WmsLevelModel).where(WmsLevelModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(WmsBayModel).where(WmsBayModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(WmsAisleModel).where(WmsAisleModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(WmsZoneModel).where(WmsZoneModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(WarehouseLocationModel).where(
                        WarehouseLocationModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(WarehouseModel).where(WarehouseModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(BranchModel).where(BranchModel.company_id.in_(company_ids))
                )


def _bin(
    data: WmsLocationFixture,
    location: WarehouseLocation,
    *,
    zone: str,
    storage_type: StorageType,
    aisle: str = "A01",
    rack: str = "R01",
    shelf: str = "S01",
    bin_code: str = "B01",
    occupied_units: int = 0,
    used_weight: Decimal = ZERO,
    used_volume: Decimal = ZERO,
    blocked: bool = False,
) -> WarehouseBin:
    return WarehouseBin(
        address=WarehouseAddress(
            company_id=data.company_id,
            warehouse_id=data.warehouse.id,
            zone=zone,
            aisle=aisle,
            rack=rack,
            shelf=shelf,
            bin=bin_code,
        ),
        inventory_location_id=location.id,
        capacity=BinCapacity(
            dimensions=BinDimensions(D("2"), D("2"), D("2")),
            max_weight=D("100"),
            max_units=10,
        ),
        storage_type=storage_type,
        occupied_units=occupied_units,
        used_weight=used_weight,
        used_volume=used_volume,
        blocked=blocked,
    )


def test_complete_cartesian_hierarchy_round_trip() -> None:
    async def scenario() -> None:
        async with wms_location_fixture() as data:
            first = _bin(
                data,
                data.locations[0],
                zone="PICK",
                storage_type=StorageType.PICKING,
            )
            second = _bin(
                data,
                data.locations[1],
                zone="PICK",
                storage_type=StorageType.PICKING,
                bin_code="B02",
            )
            async with data.database.session() as session, session.begin():
                repository = WMSLocationRepository(session, company_id=data.company_id)
                assert await repository.add(first, actor_id=data.actor_id) == first
                assert await repository.add(second, actor_id=data.actor_id) == second
                assert await repository.get(first.inventory_location_id) == first
                assert await repository.get_by_address(first.address) == first
                assert await session.scalar(select(func.count()).select_from(WmsZoneModel)) == 1
                assert await session.scalar(select(func.count()).select_from(WmsAisleModel)) == 1
                assert await session.scalar(select(func.count()).select_from(WmsBayModel)) == 1
                assert await session.scalar(select(func.count()).select_from(WmsLevelModel)) == 1

    asyncio.run(scenario())


def test_spatial_capacity_occupancy_and_zone_queries() -> None:
    async def scenario() -> None:
        async with wms_location_fixture() as data:
            bins = (
                _bin(
                    data,
                    data.locations[0],
                    zone="PICK",
                    storage_type=StorageType.PICKING,
                ),
                _bin(
                    data,
                    data.locations[1],
                    zone="RESERVE",
                    storage_type=StorageType.RESERVE,
                    occupied_units=10,
                    used_weight=D("10"),
                    used_volume=D("1"),
                ),
                _bin(
                    data,
                    data.locations[2],
                    zone="DAMAGED",
                    storage_type=StorageType.DAMAGED,
                    occupied_units=2,
                    used_weight=D("4"),
                    used_volume=D("2"),
                ),
                _bin(
                    data,
                    data.locations[3],
                    zone="QUAR",
                    storage_type=StorageType.QUARANTINE,
                    blocked=True,
                ),
            )
            async with data.database.session() as session, session.begin():
                repository = WMSLocationRepository(session, company_id=data.company_id)
                for aggregate in bins:
                    await repository.add(aggregate, actor_id=data.actor_id)
                picking = await repository.search_bins(
                    warehouse_id=data.warehouse.id,
                    zone="pick",
                    storage_types=(StorageType.PICKING,),
                    occupancy_statuses=(OccupancyStatus.EMPTY,),
                    min_available_units=5,
                    min_available_weight=D("50"),
                    min_available_volume=D("4"),
                )
                assert picking == (bins[0],)
                assert await repository.search_bins(
                    occupancy_statuses=(OccupancyStatus.FULL,)
                ) == (bins[1],)
                assert await repository.search_bins(
                    occupancy_statuses=(OccupancyStatus.PARTIAL,)
                ) == (bins[2],)
                assert await repository.search_bins(
                    occupancy_statuses=(OccupancyStatus.BLOCKED,)
                ) == (bins[3],)

    asyncio.run(scenario())


def test_optimistic_occupancy_update_has_one_version_winner() -> None:
    async def scenario() -> None:
        async with wms_location_fixture() as data:
            original = _bin(
                data,
                data.locations[0],
                zone="PICK",
                storage_type=StorageType.PICKING,
            )
            updated = original.plan_putaway(
                PutawayLoad(
                    company_id=data.company_id,
                    warehouse_id=data.warehouse.id,
                    dimensions=BinDimensions(D("1"), D("1"), D("1")),
                    unit_weight=D("2"),
                    units=2,
                    condition=StockCondition.AVAILABLE,
                ),
                PutawayPolicy(data.company_id, data.warehouse.id, ("PICK",)),
            )
            async with data.database.session() as session, session.begin():
                repository = WMSLocationRepository(session, company_id=data.company_id)
                await repository.add(original, actor_id=data.actor_id)
                assert await repository.save(
                    updated, actor_id=data.actor_id, expected_version=1
                ) == updated
                with pytest.raises(OptimisticLockError) as captured:
                    await repository.save(
                        updated, actor_id=data.actor_id, expected_version=1
                    )
                assert captured.value.code == "VERSION_CONFLICT"
                assert await repository.get(original.inventory_location_id) == updated

    asyncio.run(scenario())


def test_tenant_isolation_unique_address_and_caller_transaction() -> None:
    async def scenario() -> None:
        async with wms_location_fixture() as data:
            original = _bin(
                data,
                data.locations[0],
                zone="PICK",
                storage_type=StorageType.PICKING,
            )
            duplicate_address = replace(
                original, inventory_location_id=data.locations[1].id
            )
            async with data.database.session() as session, session.begin():
                repository = WMSLocationRepository(session, company_id=data.company_id)
                await repository.add(original, actor_id=data.actor_id)
                foreign = WMSLocationRepository(session, company_id=data.other_company_id)
                assert await foreign.get(original.inventory_location_id) is None
                assert await foreign.get_by_address(original.address) is None
                with pytest.raises(ApplicationError) as scope:
                    await foreign.add(original, actor_id=data.actor_id)
                assert scope.value.code == "SCOPE_FORBIDDEN"
                nested = await session.begin_nested()
                with pytest.raises(ApplicationError) as conflict:
                    await repository.add(duplicate_address, actor_id=data.actor_id)
                assert conflict.value.code == "WMS_LOCATION_CONFLICT"
                await nested.rollback()

            rolled_back = _bin(
                data,
                data.locations[4],
                zone="ROLLBACK",
                storage_type=StorageType.RESERVE,
            )
            async with data.database.session() as session:
                await WMSLocationRepository(session, company_id=data.company_id).add(
                    rolled_back, actor_id=data.actor_id
                )
                await session.rollback()
            async with data.database.session() as session:
                assert (
                    await WMSLocationRepository(
                        session, company_id=data.company_id
                    ).get(rolled_back.inventory_location_id)
                    is None
                )

    asyncio.run(scenario())


def test_migration_0058_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="wms"))
                    expected_tables = {
                        "wms_zone",
                        "wms_aisle",
                        "wms_bay",
                        "wms_level",
                        "wms_bin",
                        "wms_bin_capacity",
                    }
                    assert expected_tables.issubset(tables) is expected
                    if not expected:
                        return
                    unique_constraints = {
                        value["name"]
                        for value in inspector.get_unique_constraints(
                            "wms_bin", schema="wms"
                        )
                    }
                    assert "uq_wms_bin_cartesian_address" in unique_constraints
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes("wms_bin", schema="wms")
                    }
                    assert {"ix_wms_bin_spatial_address", "ix_wms_bin_occupancy"} <= indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0057")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0058")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []

"""Integration tests for company-scoped WMS PostgreSQL repositories."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete

from erp.modules.product.infrastructure import ProductRepository
from erp.modules.wms.domain.package import Package, PackageType
from erp.modules.wms.domain.picking import PickingTask, PickingWave
from erp.modules.wms.domain.shipment import Shipment
from erp.modules.wms.infrastructure import (
    PackageItemModel,
    PackageModel,
    PickingTaskModel,
    PickingWaveModel,
    ShipmentModel,
    WmsRepository,
)
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


async def _cleanup_wms(data: Fixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(
            delete(PackageItemModel).where(PackageItemModel.company_id.in_(company_ids))
        )
        await session.execute(delete(PackageModel).where(PackageModel.company_id.in_(company_ids)))
        await session.execute(
            delete(ShipmentModel).where(ShipmentModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(PickingTaskModel).where(PickingTaskModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(PickingWaveModel).where(PickingWaveModel.company_id.in_(company_ids))
        )


@asynccontextmanager
async def wms_fixture() -> AsyncIterator[Fixture]:
    async with fixture() as data:
        try:
            yield data
        finally:
            await _cleanup_wms(data)


def test_wms_repository_persists_wave_task_package_and_shipment() -> None:
    async def scenario() -> None:
        async with wms_fixture() as data:
            product = data.product(code="WMS-PROD")
            async with data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=data.company_id).add(
                    product, actor_id=data.actor_id
                )
                repository = WmsRepository(session, company_id=data.company_id)
                wave = PickingWave.create(company_id=data.company_id, code="WAVE-001")
                await repository.add_wave(wave, actor_id=data.actor_id)
                task = PickingTask.create(
                    company_id=data.company_id,
                    wave_id=wave.id,
                    sequence=1,
                    product_id=product.id,
                    requested_quantity=Decimal("3.500000"),
                )
                await repository.add_task(task, actor_id=data.actor_id)
                shipment = Shipment.create(
                    company_id=data.company_id,
                    shipment_code="SHIP-001",
                    carrier_code="CORREIOS",
                )
                await repository.add_shipment(shipment, actor_id=data.actor_id)
                package = Package.create(
                    company_id=data.company_id,
                    package_code="PKG-001",
                    package_type=PackageType.CARTON,
                    wave_id=wave.id,
                    shipment_id=shipment.id,
                    weight_grams=350,
                )
                await repository.add_package(package, actor_id=data.actor_id)

                assert await repository.get_wave(wave.id) == wave
                assert await repository.list_waves() == (wave,)
                assert await repository.list_tasks(wave_id=wave.id) == (task,)
                assert await repository.get_shipment(shipment.id) == shipment
                assert await repository.get_package(package.id) == package

    asyncio.run(scenario())


def test_wms_repository_hides_foreign_company_rows_and_rejects_scope_mismatch() -> None:
    async def scenario() -> None:
        async with wms_fixture() as data, data.database.session() as session, session.begin():
            own_repo = WmsRepository(session, company_id=data.company_id)
            foreign_repo = WmsRepository(session, company_id=data.other_company_id)
            own = PickingWave.create(company_id=data.company_id, code="OWN-WAVE")
            foreign = PickingWave.create(company_id=data.other_company_id, code="FOREIGN-WAVE")
            await own_repo.add_wave(own, actor_id=data.actor_id)
            await foreign_repo.add_wave(foreign, actor_id=data.actor_id)

            assert await own_repo.list_waves() == (own,)
            assert await foreign_repo.list_waves() == (foreign,)
            assert await own_repo.get_wave(foreign.id) is None
            with pytest.raises(ApplicationError) as captured:
                await own_repo.add_wave(
                    PickingWave.create(company_id=data.other_company_id, code="ATTACK"),
                    actor_id=data.actor_id,
                )
            assert captured.value.code == "SCOPE_FORBIDDEN"

    asyncio.run(scenario())


def test_wms_repository_rejects_duplicates_and_missing_references() -> None:
    async def scenario() -> None:
        async with wms_fixture() as data:
            async with data.database.session() as session, session.begin():
                repository = WmsRepository(session, company_id=data.company_id)
                wave = PickingWave.create(company_id=data.company_id, code="DUP-WAVE")
                await repository.add_wave(wave, actor_id=data.actor_id)
                async with session.begin_nested() as savepoint:
                    with pytest.raises(ApplicationError) as duplicate:
                        await repository.add_wave(
                            PickingWave.create(company_id=data.company_id, code=wave.code),
                            actor_id=data.actor_id,
                        )
                    assert duplicate.value.code == "WMS_PICKING_WAVE_CONFLICT"
                    await savepoint.rollback()

            async with data.database.session() as session, session.begin():
                product = data.product(code="MISSING-WMS")
                await ProductRepository(session, company_id=data.company_id).add(
                    product, actor_id=data.actor_id
                )
                repository = WmsRepository(session, company_id=data.company_id)
                missing_wave_task = PickingTask.create(
                    company_id=data.company_id,
                    wave_id=uuid4(),
                    sequence=1,
                    product_id=product.id,
                    requested_quantity="1",
                )
                with pytest.raises(ApplicationError) as missing_wave:
                    await repository.add_task(missing_wave_task, actor_id=data.actor_id)
                assert missing_wave.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())

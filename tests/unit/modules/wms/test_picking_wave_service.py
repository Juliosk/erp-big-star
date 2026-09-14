"""Application service tests for M10 picking-wave orchestration."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.wms.application.permissions import WMS_PICK_EXECUTE, WmsAuthorization
from erp.modules.wms.application.waves import (
    CreatePickingWave,
    PickingTaskBatchItem,
    PickingWaveDetail,
    PickingWaveService,
    WmsPage,
    WmsWaveStore,
)
from erp.modules.wms.domain.picking import PickingTask, PickingWave, PickingWaveStatus
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
        self.created: PickingWaveDetail | None = None

    async def create_wave(
        self, wave: PickingWave, tasks: tuple[PickingTask, ...], actor_id: UUID
    ) -> PickingWaveDetail:
        self.created = PickingWaveDetail(wave=wave, tasks=tasks)
        return self.created

    async def list_waves(
        self,
        company_id: UUID,
        *,
        status: PickingWaveStatus | None,
        page: int,
        page_size: int,
    ) -> WmsPage[PickingWave]:
        items = (self.created.wave,) if self.created is not None else ()
        return WmsPage(items=items, page=page, page_size=page_size, has_more=False)

    async def get_wave(self, company_id: UUID, wave_id: UUID) -> PickingWaveDetail | None:
        if self.created is not None and self.created.wave.id == wave_id:
            return self.created
        return None


def _context(user_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(user_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(),
        scopes=frozenset(),
    )


def test_picking_wave_service_authorizes_and_batches_tasks_by_zone() -> None:
    async def scenario() -> None:
        company_id, actor_id = uuid4(), uuid4()
        product_a, product_b, product_c = uuid4(), uuid4(), uuid4()
        authorization = FakeAuthorization()
        store = FakeStore()
        service = PickingWaveService(
            cast(WmsWaveStore, store), cast(WmsAuthorization, authorization)
        )

        detail = await service.create_wave(
            _context(actor_id),
            CreatePickingWave(
                company_id=company_id,
                code=" wave-001 ",
                items=(
                    PickingTaskBatchItem(product_id=product_b, quantity="2", zone_code="Z-B"),
                    PickingTaskBatchItem(product_id=product_a, quantity="1", zone_code="Z-A"),
                    PickingTaskBatchItem(product_id=product_c, quantity="3", zone_code="Z-A"),
                ),
            ),
        )

        assert detail.wave.code == "WAVE-001"
        assert [task.sequence for task in detail.tasks] == [1, 2, 3]
        assert [task.product_id for task in detail.tasks] == [product_a, product_c, product_b]
        assert authorization.calls == [(company_id, WMS_PICK_EXECUTE, True)]

    asyncio.run(scenario())


def test_picking_wave_service_queries_authorize_and_translate_missing_wave() -> None:
    async def scenario() -> None:
        company_id, actor_id = uuid4(), uuid4()
        authorization = FakeAuthorization()
        service = PickingWaveService(
            cast(WmsWaveStore, FakeStore()), cast(WmsAuthorization, authorization)
        )

        page = await service.list_waves(_context(actor_id), company_id, page=2, page_size=10)
        assert page.items == ()
        assert page.page == 2
        assert authorization.calls == [(company_id, WMS_PICK_EXECUTE, False)]

        with pytest.raises(ApplicationError) as missing:
            await service.get_wave(_context(actor_id), company_id, uuid4())
        assert missing.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "command",
    [
        CreatePickingWave(company_id=uuid4(), code="EMPTY", items=()),
        CreatePickingWave(
            company_id=uuid4(),
            code="BAD-ZONE",
            items=(PickingTaskBatchItem(product_id=uuid4(), quantity="1", zone_code="bad zone"),),
        ),
    ],
)
def test_picking_wave_service_translates_validation_to_error_contract(
    command: CreatePickingWave,
) -> None:
    async def scenario() -> None:
        service = PickingWaveService(
            cast(WmsWaveStore, FakeStore()), cast(WmsAuthorization, FakeAuthorization())
        )

        with pytest.raises(ApplicationError) as captured:
            await service.create_wave(_context(uuid4()), command)
        assert captured.value.code == "BUSINESS_VALIDATION_ERROR"
        assert captured.value.status_code == 422

    asyncio.run(scenario())

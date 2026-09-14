"""Session-owning PostgreSQL adapter for M10 picking-wave application services."""

from uuid import UUID

from erp.modules.wms.application.waves import PickingWaveDetail, WmsPage, WmsWaveStore
from erp.modules.wms.domain.picking import PickingTask, PickingWave, PickingWaveStatus
from erp.modules.wms.infrastructure.repository import WmsRepository
from erp.platform.database import Database


class PostgresPickingWaveStore(WmsWaveStore):
    """Create and query picking waves through tenant-bound repositories."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_wave(
        self, wave: PickingWave, tasks: tuple[PickingTask, ...], actor_id: UUID
    ) -> PickingWaveDetail:
        async with self._database.session() as session, session.begin():
            repository = WmsRepository(session, company_id=wave.company_id)
            await repository.add_wave(wave, actor_id=actor_id)
            for task in tasks:
                await repository.add_task(task, actor_id=actor_id)
        return PickingWaveDetail(wave=wave, tasks=tasks)

    async def list_waves(
        self,
        company_id: UUID,
        *,
        status: PickingWaveStatus | None,
        page: int,
        page_size: int,
    ) -> WmsPage[PickingWave]:
        offset = (page - 1) * page_size
        async with self._database.session() as session:
            repository = WmsRepository(session, company_id=company_id)
            items = await repository.list_waves(status=status, limit=page_size, offset=offset)
            more = await repository.list_waves(status=status, limit=1, offset=offset + page_size)
        return WmsPage(items=items, page=page, page_size=page_size, has_more=bool(more))

    async def get_wave(self, company_id: UUID, wave_id: UUID) -> PickingWaveDetail | None:
        async with self._database.session() as session:
            repository = WmsRepository(session, company_id=company_id)
            wave = await repository.get_wave(wave_id)
            if wave is None:
                return None
            tasks = await repository.list_tasks(wave_id=wave_id)
        return PickingWaveDetail(wave=wave, tasks=tasks)


__all__ = ["PostgresPickingWaveStore"]

"""PostgreSQL adapter for executable M10 picking tasks."""

from uuid import UUID

from erp.modules.wms.application.picking import (
    PickingTaskCommandResult,
    ScanPickingTask,
    WmsPickingTaskStore,
)
from erp.modules.wms.domain.picking import PickingWaveStatus
from erp.modules.wms.infrastructure.effects import WmsEffects
from erp.modules.wms.infrastructure.repository import WmsRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresPickingTaskStore(WmsPickingTaskStore):
    """Execute scan commands inside one idempotent, tenant-bound transaction."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def scan_task(
        self, command: ScanPickingTask, actor_id: UUID
    ) -> PickingTaskCommandResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"wms:{command.company_id}:{actor_id}",
                operation="wms.picking-task.scan",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored WMS picking-task replay has no body.")
                return PickingTaskCommandResult.replay(decision.response_body)
            repository = WmsRepository(session, company_id=command.company_id)
            task = await repository.get_task_for_update(command.task_id)
            if task is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Picking task not found.",
                    status_code=404,
                )
            wave = await repository.get_wave_for_update(task.wave_id)
            if wave is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Picking wave not found.",
                    status_code=404,
                )
            if wave.status not in {PickingWaveStatus.RELEASED, PickingWaveStatus.IN_PROGRESS}:
                raise ApplicationError(
                    code="WMS_PICKING_WAVE_STATUS_CONFLICT",
                    message="Picking task can be scanned only after wave release.",
                    status_code=409,
                )
            scanned = await repository.scan_task(
                task,
                actor_id=actor_id,
                barcode=command.barcode,
                quantity=f"{command.quantity:.6f}",
            )
            result = await WmsEffects().record_task_scan(
                session,
                scanned,
                actor_id=actor_id,
                metadata=command.metadata,
                before=task,
                barcode=command.barcode,
            )
            await self._idempotency.complete(
                session,
                decision,
                response_status=200,
                response_body=result.to_dict(),
            )
            return result


__all__ = ["PostgresPickingTaskStore"]

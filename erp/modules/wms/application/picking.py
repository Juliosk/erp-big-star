"""Application service for executable WMS picking tasks."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from erp.modules.admin.contracts import PermissionCode, SecurityContext
from erp.modules.wms.application.permissions import WMS_PICK_EXECUTE, WmsAuthorization
from erp.modules.wms.application.waves import CommandMetadata, picking_task_snapshot
from erp.modules.wms.domain.picking import PickingTask, PickingTaskStatus


@dataclass(frozen=True, slots=True)
class ScanPickingTask:
    company_id: UUID
    task_id: UUID
    barcode: str
    quantity: Decimal
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "task_id": str(self.task_id),
            "barcode": self.barcode.strip().upper(),
            "quantity": f"{self.quantity:.6f}",
        }


@dataclass(frozen=True, slots=True)
class PickingTaskCommandResult:
    task: PickingTask
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "task": picking_task_snapshot(self.task),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id)
            if self.audit_event_id is not None
            else None,
            "idempotency_replayed": self.idempotency_replayed,
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> PickingTaskCommandResult:
        task = body["task"]
        if not isinstance(task, dict):
            raise ValueError("Stored WMS picking-task replay has invalid body.")
        return cls(
            task=_task_from_snapshot(task),
            event_id=UUID(str(body["event_id"])) if body["event_id"] is not None else None,
            audit_event_id=UUID(str(body["audit_event_id"]))
            if body["audit_event_id"] is not None
            else None,
            idempotency_replayed=True,
        )


class WmsPickingTaskStore(Protocol):
    async def scan_task(
        self, command: ScanPickingTask, actor_id: UUID
    ) -> PickingTaskCommandResult: ...


class WmsPickingTaskAuthorizer(Protocol):
    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: PermissionCode,
        *,
        write: bool = False,
    ) -> None: ...


class PickingTaskScanService:
    """Authorize scan commands and delegate the atomic mutation to storage."""

    def __init__(self, store: WmsPickingTaskStore, authorization: WmsAuthorization) -> None:
        self._store = store
        self._authorization: WmsPickingTaskAuthorizer = authorization

    async def scan(
        self, context: SecurityContext, command: ScanPickingTask
    ) -> PickingTaskCommandResult:
        await self._authorization.require(
            context, command.company_id, WMS_PICK_EXECUTE, write=True
        )
        return await self._store.scan_task(command, context.principal.user_id)


def _task_from_snapshot(snapshot: dict[str, object]) -> PickingTask:
    return PickingTask(
        id=UUID(str(snapshot["id"])),
        company_id=UUID(str(snapshot["company_id"])),
        wave_id=UUID(str(snapshot["wave_id"])),
        sequence=int(str(snapshot["sequence"])),
        product_id=UUID(str(snapshot["product_id"])),
        warehouse_id=(
            UUID(str(snapshot["warehouse_id"])) if snapshot["warehouse_id"] is not None else None
        ),
        lot_id=UUID(str(snapshot["lot_id"])) if snapshot["lot_id"] is not None else None,
        pool_id=UUID(str(snapshot["pool_id"])) if snapshot["pool_id"] is not None else None,
        requested_quantity=Decimal(str(snapshot["requested_quantity"])),
        picked_quantity=Decimal(str(snapshot["picked_quantity"])),
        status=PickingTaskStatus(str(snapshot["status"])),
        version=int(str(snapshot["version"])),
    )


__all__ = [
    "PickingTaskCommandResult",
    "PickingTaskScanService",
    "ScanPickingTask",
    "WmsPickingTaskStore",
]

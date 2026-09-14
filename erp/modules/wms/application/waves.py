"""Application service for M10 picking-wave orchestration."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from erp.modules.admin.contracts import PermissionCode, SecurityContext
from erp.modules.wms.application.permissions import WMS_PICK_EXECUTE, WmsAuthorization
from erp.modules.wms.domain.picking import (
    PickingTask,
    PickingTaskStatus,
    PickingWave,
    PickingWaveStatus,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class WmsPage[T]:
    items: tuple[T, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class PickingTaskBatchItem:
    product_id: UUID
    quantity: Decimal | str
    zone_code: str = "DEFAULT"
    warehouse_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreatePickingWave:
    company_id: UUID
    code: str
    items: tuple[PickingTaskBatchItem, ...]
    source_type: str = "MANUAL"
    source_id: UUID | None = None
    warehouse_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class ReleasePickingWave:
    company_id: UUID
    wave_id: UUID
    expected_version: int
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "wave_id": str(self.wave_id),
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True, slots=True)
class PickingWaveDetail:
    wave: PickingWave
    tasks: tuple[PickingTask, ...]


@dataclass(frozen=True, slots=True)
class WmsCommandResult:
    detail: PickingWaveDetail
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "detail": picking_wave_detail_snapshot(self.detail),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id)
            if self.audit_event_id is not None
            else None,
            "idempotency_replayed": self.idempotency_replayed,
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> WmsCommandResult:
        detail = body["detail"]
        if not isinstance(detail, dict):
            raise ValueError("Stored WMS replay has invalid body.")
        return cls(
            detail=picking_wave_detail_from_snapshot(detail),
            event_id=UUID(str(body["event_id"])) if body["event_id"] is not None else None,
            audit_event_id=UUID(str(body["audit_event_id"]))
            if body["audit_event_id"] is not None
            else None,
            idempotency_replayed=True,
        )


class WmsAuthorizer(Protocol):
    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: PermissionCode,
        *,
        write: bool = False,
    ) -> None: ...


class WmsWaveStore(Protocol):
    async def create_wave(
        self, wave: PickingWave, tasks: tuple[PickingTask, ...], actor_id: UUID
    ) -> PickingWaveDetail: ...

    async def list_waves(
        self,
        company_id: UUID,
        *,
        status: PickingWaveStatus | None,
        page: int,
        page_size: int,
    ) -> WmsPage[PickingWave]: ...

    async def get_wave(self, company_id: UUID, wave_id: UUID) -> PickingWaveDetail | None: ...

    async def release_wave(
        self, command: ReleasePickingWave, actor_id: UUID
    ) -> WmsCommandResult: ...


class PickingWaveService:
    """Authorize and build picking waves without leaking persistence details."""

    def __init__(self, store: WmsWaveStore, authorization: WmsAuthorization) -> None:
        self._store = store
        self._authorization: WmsAuthorizer = authorization

    async def create_wave(
        self, context: SecurityContext, command: CreatePickingWave
    ) -> PickingWaveDetail:
        await self._authorization.require(
            context, command.company_id, WMS_PICK_EXECUTE, write=True
        )
        if not command.items:
            raise _validation("A picking wave requires at least one task.")
        try:
            wave = PickingWave.create(
                company_id=command.company_id,
                code=command.code,
                source_type=command.source_type,
                source_id=command.source_id,
                warehouse_id=command.warehouse_id,
            )
            tasks = tuple(
                PickingTask.create(
                    company_id=command.company_id,
                    wave_id=wave.id,
                    sequence=index,
                    product_id=item.product_id,
                    requested_quantity=item.quantity,
                    warehouse_id=item.warehouse_id or command.warehouse_id,
                    lot_id=item.lot_id,
                    pool_id=item.pool_id,
                )
                for index, item in enumerate(_items_by_zone(command.items), start=1)
            )
        except ValueError as error:
            raise _validation(str(error)) from error
        return await self._store.create_wave(wave, tasks, context.principal.user_id)

    async def list_waves(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        status: PickingWaveStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> WmsPage[PickingWave]:
        await self._authorization.require(context, company_id, WMS_PICK_EXECUTE)
        _validate_page(page, page_size)
        if status is not None and not isinstance(status, PickingWaveStatus):
            raise _validation("Invalid picking wave status.")
        return await self._store.list_waves(
            company_id, status=status, page=page, page_size=page_size
        )

    async def get_wave(
        self, context: SecurityContext, company_id: UUID, wave_id: UUID
    ) -> PickingWaveDetail:
        await self._authorization.require(context, company_id, WMS_PICK_EXECUTE)
        detail = await self._store.get_wave(company_id, wave_id)
        if detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Picking wave not found.",
                status_code=404,
            )
        return detail

    async def release_wave(
        self, context: SecurityContext, command: ReleasePickingWave
    ) -> WmsCommandResult:
        await self._authorization.require(
            context, command.company_id, WMS_PICK_EXECUTE, write=True
        )
        return await self._store.release_wave(command, context.principal.user_id)


def picking_wave_snapshot(wave: PickingWave) -> dict[str, object]:
    return {
        "id": str(wave.id),
        "company_id": str(wave.company_id),
        "code": wave.code,
        "status": wave.status,
        "source_type": wave.source_type,
        "source_id": str(wave.source_id) if wave.source_id is not None else None,
        "warehouse_id": str(wave.warehouse_id) if wave.warehouse_id is not None else None,
        "released_at": wave.released_at.isoformat() if wave.released_at is not None else None,
        "released_by": str(wave.released_by) if wave.released_by is not None else None,
        "version": wave.version,
    }


def picking_task_snapshot(task: PickingTask) -> dict[str, object]:
    return {
        "id": str(task.id),
        "company_id": str(task.company_id),
        "wave_id": str(task.wave_id),
        "sequence": task.sequence,
        "product_id": str(task.product_id),
        "warehouse_id": str(task.warehouse_id) if task.warehouse_id is not None else None,
        "lot_id": str(task.lot_id) if task.lot_id is not None else None,
        "pool_id": str(task.pool_id) if task.pool_id is not None else None,
        "requested_quantity": f"{task.requested_quantity:.6f}",
        "picked_quantity": f"{task.picked_quantity:.6f}",
        "status": task.status,
        "version": task.version,
    }


def picking_wave_detail_snapshot(detail: PickingWaveDetail) -> dict[str, object]:
    return {
        "wave": picking_wave_snapshot(detail.wave),
        "tasks": [picking_task_snapshot(task) for task in detail.tasks],
    }


def picking_wave_detail_from_snapshot(snapshot: dict[str, object]) -> PickingWaveDetail:
    wave = snapshot["wave"]
    tasks = snapshot["tasks"]
    if not isinstance(wave, dict) or not isinstance(tasks, list):
        raise ValueError("Stored WMS detail replay has invalid snapshots.")
    return PickingWaveDetail(
        wave=PickingWave(
            id=UUID(str(wave["id"])),
            company_id=UUID(str(wave["company_id"])),
            code=str(wave["code"]),
            status=PickingWaveStatus(str(wave["status"])),
            source_type=str(wave["source_type"]),
            source_id=UUID(str(wave["source_id"])) if wave["source_id"] is not None else None,
            warehouse_id=(
                UUID(str(wave["warehouse_id"])) if wave["warehouse_id"] is not None else None
            ),
            released_at=(
                datetime.fromisoformat(str(wave["released_at"]))
                if wave["released_at"] is not None
                else None
            ),
            released_by=(
                UUID(str(wave["released_by"])) if wave["released_by"] is not None else None
            ),
            version=int(str(wave["version"])),
        ),
        tasks=tuple(_task_from_snapshot(item) for item in tasks if isinstance(item, dict)),
    )


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


def _items_by_zone(items: tuple[PickingTaskBatchItem, ...]) -> tuple[PickingTaskBatchItem, ...]:
    indexed = tuple((index, _normalize_zone(item.zone_code), item) for index, item in enumerate(items))
    return tuple(item for _, _, item in sorted(indexed, key=lambda entry: (entry[1], entry[0])))


def _normalize_zone(value: str) -> str:
    zone = value.strip().upper()
    if not zone or len(zone) > 32:
        raise ValueError("zone_code must be 1-32 characters.")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not zone[0].isalnum() or any(char not in allowed for char in zone):
        raise ValueError("zone_code must use uppercase alphanumeric code format.")
    return zone


def _validate_page(page: int, page_size: int) -> None:
    if type(page) is not int or not 1 <= page <= 100_000:
        raise _validation("Invalid page.")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise _validation("Invalid page size.")


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid picking wave data.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "CommandMetadata",
    "CreatePickingWave",
    "PickingTaskBatchItem",
    "PickingWaveDetail",
    "PickingWaveService",
    "ReleasePickingWave",
    "WmsCommandResult",
    "WmsPage",
    "WmsWaveStore",
    "picking_task_snapshot",
    "picking_wave_detail_from_snapshot",
    "picking_wave_detail_snapshot",
    "picking_wave_snapshot",
]

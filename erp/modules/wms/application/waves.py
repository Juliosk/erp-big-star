"""Application service for M10 picking-wave orchestration."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import PermissionCode, SecurityContext
from erp.modules.wms.application.permissions import WMS_PICK_EXECUTE, WmsAuthorization
from erp.modules.wms.domain.picking import PickingTask, PickingWave, PickingWaveStatus
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
class PickingWaveDetail:
    wave: PickingWave
    tasks: tuple[PickingTask, ...]


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
    "CreatePickingWave",
    "PickingTaskBatchItem",
    "PickingWaveDetail",
    "PickingWaveService",
    "WmsPage",
    "WmsWaveStore",
]

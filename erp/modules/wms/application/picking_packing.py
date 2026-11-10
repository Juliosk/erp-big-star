"""Use cases for route-aware picking, barcode packing and manifests."""

from collections.abc import Awaitable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypeVar
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.wms.application.permissions import (
    WMS_DISPATCH_EXECUTE,
    WMS_INVENTORY_MOVEMENT,
    WMS_PACK_EXECUTE,
    WMS_PICK_EXECUTE,
    WmsAuthorization,
)
from erp.modules.wms.application.waves import CommandMetadata
from erp.modules.wms.domain import (
    ExpeditionManifest,
    PickingPackingItem,
    PickingPackingWave,
    WmsLocationError,
    WmsPickingPackingError,
)
from erp.platform.errors import ApplicationError, ErrorDetail

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PickingDemand:
    sales_order_id: UUID
    shipment_id: UUID
    product_id: UUID
    bin_id: UUID
    barcode: str
    quantity: Decimal
    units: int
    unit_weight: Decimal
    unit_volume: Decimal
    lot_id: UUID | None = None
    pool_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreatePickingPackingWave:
    company_id: UUID
    warehouse_id: UUID
    code: str
    demands: tuple[PickingDemand, ...]
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class ExecutePickingRoute:
    company_id: UUID
    wave_id: UUID
    expected_version: int
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class VerifyPackingScan:
    company_id: UUID
    wave_id: UUID
    barcode: str
    quantity: Decimal
    scan_key: str
    expected_version: int
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class GenerateExpeditionManifest:
    company_id: UUID
    wave_id: UUID
    expected_version: int
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class PickingPackingWaveDetail:
    wave: PickingPackingWave
    items: tuple[PickingPackingItem, ...]
    inventory_transaction_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PackingScanResult:
    detail: PickingPackingWaveDetail
    verified_item_id: UUID
    verification_id: UUID
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ExpeditionManifestResult:
    detail: PickingPackingWaveDetail
    manifest: ExpeditionManifest


class WmsPickingPackingStore(Protocol):
    async def create_wave(
        self, command: CreatePickingPackingWave, actor_id: UUID
    ) -> PickingPackingWaveDetail: ...

    async def execute_route(
        self, command: ExecutePickingRoute, actor_id: UUID
    ) -> PickingPackingWaveDetail: ...

    async def verify_scan(
        self, command: VerifyPackingScan, actor_id: UUID
    ) -> PackingScanResult: ...

    async def generate_manifest(
        self, command: GenerateExpeditionManifest, actor_id: UUID
    ) -> ExpeditionManifestResult: ...


class WMSPickingPackingService:
    """Authorize the use cases while PostgreSQL owns atomic state changes."""

    def __init__(self, store: WmsPickingPackingStore, authorization: WmsAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create_wave(
        self, context: SecurityContext, command: CreatePickingPackingWave
    ) -> PickingPackingWaveDetail:
        await self._authorization.require(context, command.company_id, WMS_PICK_EXECUTE, write=True)
        _validate_create(command)
        return await self._translate(self._store.create_wave(command, context.principal.user_id))

    async def execute_route(
        self, context: SecurityContext, command: ExecutePickingRoute
    ) -> PickingPackingWaveDetail:
        await self._authorization.require(context, command.company_id, WMS_PICK_EXECUTE, write=True)
        await self._authorization.require(
            context, command.company_id, WMS_INVENTORY_MOVEMENT, write=True
        )
        _validate_mutation(command.company_id, command.wave_id, command.expected_version)
        return await self._translate(self._store.execute_route(command, context.principal.user_id))

    async def verify_scan(
        self, context: SecurityContext, command: VerifyPackingScan
    ) -> PackingScanResult:
        await self._authorization.require(context, command.company_id, WMS_PACK_EXECUTE, write=True)
        _validate_mutation(command.company_id, command.wave_id, command.expected_version)
        if (
            not isinstance(command.barcode, str)
            or not command.barcode
            or command.barcode != command.barcode.strip().upper()
        ):
            raise _validation("barcode must be canonical uppercase text.")
        if (
            not isinstance(command.scan_key, str)
            or not 1 <= len(command.scan_key) <= 128
            or command.scan_key != command.scan_key.strip()
        ):
            raise _validation("scan_key must contain 1 to 128 trimmed characters.")
        _positive_decimal(command.quantity, "quantity")
        return await self._translate(self._store.verify_scan(command, context.principal.user_id))

    async def generate_manifest(
        self, context: SecurityContext, command: GenerateExpeditionManifest
    ) -> ExpeditionManifestResult:
        await self._authorization.require(
            context, command.company_id, WMS_DISPATCH_EXECUTE, write=True
        )
        _validate_mutation(command.company_id, command.wave_id, command.expected_version)
        return await self._translate(
            self._store.generate_manifest(command, context.principal.user_id)
        )

    @staticmethod
    async def _translate(awaitable: Awaitable[T]) -> T:
        try:
            return await awaitable
        except (WmsPickingPackingError, WmsLocationError) as error:
            raise ApplicationError(
                code=error.code,
                message="WMS picking or packing operation could not be completed.",
                status_code=409,
                details=[ErrorDetail(message=str(error))],
            ) from error


def _validate_create(command: CreatePickingPackingWave) -> None:
    _identity(command.company_id, "company_id")
    _identity(command.warehouse_id, "warehouse_id")
    if not isinstance(command.code, str) or not command.code:
        raise _validation("code is required.")
    if not isinstance(command.demands, tuple) or not command.demands:
        raise _validation("at least one picking demand is required.")
    for demand in command.demands:
        if not isinstance(demand, PickingDemand):
            raise _validation("demands must contain PickingDemand values.")
        for name, value in (
            ("sales_order_id", demand.sales_order_id),
            ("shipment_id", demand.shipment_id),
            ("product_id", demand.product_id),
            ("bin_id", demand.bin_id),
        ):
            _identity(value, name)
        _positive_decimal(demand.quantity, "quantity")
        _positive_decimal(demand.unit_weight, "unit_weight")
        _positive_decimal(demand.unit_volume, "unit_volume")
        if type(demand.units) is not int or demand.units < 1:
            raise _validation("units must be a positive integer.")
        if demand.quantity != Decimal(demand.units):
            raise _validation("quantity must equal physical units.")


def _validate_mutation(company_id: UUID, wave_id: UUID, version: int) -> None:
    _identity(company_id, "company_id")
    _identity(wave_id, "wave_id")
    if type(version) is not int or version < 1:
        raise _validation("expected_version must be positive.")


def _identity(value: UUID, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise _validation(f"{field} must be a non-zero UUID.")


def _positive_decimal(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise _validation(f"{field} must be a positive finite Decimal.")


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid WMS picking or packing command.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "CreatePickingPackingWave",
    "ExecutePickingRoute",
    "ExpeditionManifestResult",
    "GenerateExpeditionManifest",
    "PackingScanResult",
    "PickingDemand",
    "PickingPackingWaveDetail",
    "VerifyPackingScan",
    "WMSPickingPackingService",
    "WmsPickingPackingStore",
]

"""Application contracts for atomic physical placement into WMS bins."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.contracts import InventoryBalanceReference
from erp.modules.wms.application.permissions import (
    WMS_INVENTORY_MOVEMENT,
    WmsAuthorization,
)
from erp.modules.wms.application.waves import CommandMetadata
from erp.modules.wms.domain import (
    BinCapacity,
    BinDimensions,
    StockCondition,
    StorageType,
    WarehouseAddress,
    WarehouseBin,
    WmsLocationError,
)
from erp.platform.errors import ApplicationError, ErrorDetail


class PutawaySourceType(StrEnum):
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    PRODUCTION_OUTPUT = "PRODUCTION_OUTPUT"


@dataclass(frozen=True, slots=True)
class ExecutePutaway:
    company_id: UUID
    warehouse_id: UUID
    product_id: UUID
    source_location_id: UUID
    target_bin_id: UUID
    source_type: PutawaySourceType
    source_id: UUID
    quantity: Decimal
    units: int
    unit_weight: Decimal
    dimensions: BinDimensions
    condition: StockCondition
    allowed_zones: tuple[str, ...]
    expected_bin_version: int
    idempotency_key: str
    metadata: CommandMetadata
    lot_id: UUID | None = None
    pool_id: UUID | None = None

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "warehouse_id": str(self.warehouse_id),
            "product_id": str(self.product_id),
            "source_location_id": str(self.source_location_id),
            "target_bin_id": str(self.target_bin_id),
            "source_type": self.source_type,
            "source_id": str(self.source_id),
            "quantity": str(self.quantity),
            "units": self.units,
            "unit_weight": str(self.unit_weight),
            "dimensions": {
                "width": str(self.dimensions.width),
                "depth": str(self.dimensions.depth),
                "height": str(self.dimensions.height),
            },
            "condition": self.condition,
            "allowed_zones": list(self.allowed_zones),
            "expected_bin_version": self.expected_bin_version,
            "lot_id": str(self.lot_id) if self.lot_id is not None else None,
            "pool_id": str(self.pool_id) if self.pool_id is not None else None,
        }


@dataclass(frozen=True, slots=True)
class WmsPutawayResult:
    transaction_id: UUID
    target_bin: WarehouseBin
    source_balance: InventoryBalanceReference
    destination_balance: InventoryBalanceReference
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": str(self.transaction_id),
            "target_bin": putaway_bin_snapshot(self.target_bin),
            "source_balance": putaway_balance_snapshot(self.source_balance),
            "destination_balance": putaway_balance_snapshot(self.destination_balance),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": (
                str(self.audit_event_id) if self.audit_event_id is not None else None
            ),
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> WmsPutawayResult:
        target_bin = body.get("target_bin")
        source = body.get("source_balance")
        destination = body.get("destination_balance")
        if not isinstance(target_bin, dict):
            raise ValueError("Stored WMS putaway replay has invalid snapshots.")
        if not isinstance(source, dict) or not isinstance(destination, dict):
            raise ValueError("Stored WMS putaway replay has invalid snapshots.")
        return cls(
            transaction_id=UUID(str(body["transaction_id"])),
            target_bin=_bin_from_snapshot(target_bin),
            source_balance=_balance_from_snapshot(source),
            destination_balance=_balance_from_snapshot(destination),
            event_id=UUID(str(body["event_id"])) if body.get("event_id") else None,
            audit_event_id=(
                UUID(str(body["audit_event_id"]))
                if body.get("audit_event_id")
                else None
            ),
            idempotency_replayed=True,
        )


class WmsPutawayStore(Protocol):
    async def putaway(
        self, command: ExecutePutaway, actor_id: UUID
    ) -> WmsPutawayResult: ...


class WMSPutawayService:
    """Authorize one putaway while persistence owns the transaction boundary."""

    def __init__(self, store: WmsPutawayStore, authorization: WmsAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def putaway(
        self, context: SecurityContext, command: ExecutePutaway
    ) -> WmsPutawayResult:
        await self._authorization.require(
            context, command.company_id, WMS_INVENTORY_MOVEMENT, write=True
        )
        _validate_command(command)
        try:
            return await self._store.putaway(command, context.principal.user_id)
        except WmsLocationError as error:
            raise ApplicationError(
                code=error.code,
                message="WMS putaway could not be completed.",
                status_code=409,
                details=[ErrorDetail(message=str(error))],
            ) from error


def _validate_command(command: ExecutePutaway) -> None:
    identities = (
        command.company_id,
        command.warehouse_id,
        command.product_id,
        command.source_location_id,
        command.target_bin_id,
        command.source_id,
    )
    if any(not isinstance(value, UUID) or value.int == 0 for value in identities):
        raise _validation("Putaway identities must be non-zero UUIDs.")
    if command.source_location_id == command.target_bin_id:
        raise _validation("Source staging location and target bin must differ.")
    if not isinstance(command.source_type, PutawaySourceType):
        raise _validation("source_type must identify purchases or production.")
    if not isinstance(command.quantity, Decimal) or not command.quantity.is_finite():
        raise _validation("quantity must be a finite Decimal.")
    exponent = command.quantity.as_tuple().exponent
    if command.quantity <= 0 or not isinstance(exponent, int) or exponent < -6:
        raise _validation("quantity must be positive with at most six decimal places.")
    if type(command.expected_bin_version) is not int or command.expected_bin_version < 1:
        raise _validation("expected_bin_version must be a positive integer.")
    if not isinstance(command.condition, StockCondition):
        raise _validation("condition must be an official stock condition.")
    if not isinstance(command.dimensions, BinDimensions):
        raise _validation("dimensions must be a validated BinDimensions value.")


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid WMS putaway command.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


def putaway_bin_snapshot(value: WarehouseBin) -> dict[str, object]:
    return {
        "company_id": str(value.address.company_id),
        "warehouse_id": str(value.address.warehouse_id),
        "address": value.address.code,
        "inventory_location_id": str(value.inventory_location_id),
        "capacity": {
            "width": str(value.capacity.dimensions.width),
            "depth": str(value.capacity.dimensions.depth),
            "height": str(value.capacity.dimensions.height),
            "max_weight": str(value.capacity.max_weight),
            "max_units": value.capacity.max_units,
        },
        "storage_type": value.storage_type,
        "occupied_units": value.occupied_units,
        "used_weight": str(value.used_weight),
        "used_volume": str(value.used_volume),
        "blocked": value.blocked,
        "version": value.version,
    }


def _bin_from_snapshot(value: dict[str, Any]) -> WarehouseBin:
    capacity = value["capacity"]
    if not isinstance(capacity, dict):
        raise ValueError("Stored WMS bin capacity snapshot is invalid.")
    return WarehouseBin(
        address=WarehouseAddress.parse(
            company_id=UUID(str(value["company_id"])),
            warehouse_id=UUID(str(value["warehouse_id"])),
            code=str(value["address"]),
        ),
        inventory_location_id=UUID(str(value["inventory_location_id"])),
        capacity=BinCapacity(
            dimensions=BinDimensions(
                Decimal(str(capacity["width"])),
                Decimal(str(capacity["depth"])),
                Decimal(str(capacity["height"])),
            ),
            max_weight=Decimal(str(capacity["max_weight"])),
            max_units=int(str(capacity["max_units"])),
        ),
        storage_type=StorageType(str(value["storage_type"])),
        occupied_units=int(str(value["occupied_units"])),
        used_weight=Decimal(str(value["used_weight"])),
        used_volume=Decimal(str(value["used_volume"])),
        blocked=bool(value["blocked"]),
        version=int(str(value["version"])),
    )


def putaway_balance_snapshot(value: InventoryBalanceReference) -> dict[str, object]:
    return {
        "company_id": str(value.company_id),
        "product_id": str(value.product_id),
        "warehouse_id": str(value.warehouse_id),
        "location_id": str(value.location_id) if value.location_id else None,
        "lot_id": str(value.lot_id) if value.lot_id else None,
        "pool_id": str(value.pool_id) if value.pool_id else None,
        "state": value.state,
        "on_hand": str(value.on_hand),
        "reserved": str(value.reserved),
        "available": str(value.available),
        "version": value.version,
    }


def _balance_from_snapshot(value: dict[str, Any]) -> InventoryBalanceReference:
    return InventoryBalanceReference(
        company_id=UUID(str(value["company_id"])),
        product_id=UUID(str(value["product_id"])),
        warehouse_id=UUID(str(value["warehouse_id"])),
        location_id=UUID(str(value["location_id"])) if value["location_id"] else None,
        lot_id=UUID(str(value["lot_id"])) if value["lot_id"] else None,
        pool_id=UUID(str(value["pool_id"])) if value["pool_id"] else None,
        state=str(value["state"]),
        on_hand=Decimal(str(value["on_hand"])),
        reserved=Decimal(str(value["reserved"])),
        available=Decimal(str(value["available"])),
        version=int(str(value["version"])),
    )


__all__ = [
    "ExecutePutaway",
    "PutawaySourceType",
    "WMSPutawayService",
    "WmsPutawayResult",
    "WmsPutawayStore",
    "putaway_balance_snapshot",
    "putaway_bin_snapshot",
]

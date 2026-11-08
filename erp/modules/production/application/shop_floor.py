"""Transactional shop-floor execution use cases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from erp.modules.inventory.contracts import (
    ConsumeProductionMaterialsContract,
    ProductionMaterialConsumptionGateway,
    ProductionMaterialConsumptionLineContract,
)
from erp.modules.production.application.events import (
    ProductionDomainEvent,
    ProductionEventPublisher,
    ProductionEventType,
)
from erp.modules.production.domain import (
    InvalidProductionValueError,
    ProductionConflictError,
    ProductionLotTrace,
    ProductionOperationStatus,
    ProductionOrder,
    ProductionQuantity,
    ProductionVersionConflictError,
    WorkCenter,
    WorkCenterCode,
)


class ShopFloorEventType(StrEnum):
    STARTED = "STARTED"
    PROGRESS = "PROGRESS"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class MaterialConsumption:
    product_id: UUID
    quantity: Decimal

    def __post_init__(self) -> None:
        _uuid(self.product_id, "product_id")
        _positive_decimal(self.quantity, "quantity")


@dataclass(frozen=True, slots=True)
class ScrapEntry:
    product_id: UUID
    quantity: Decimal
    reason_code: str
    notes: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.product_id, "product_id")
        _positive_decimal(self.quantity, "quantity")
        reason = self.reason_code.strip().upper()
        if re.fullmatch(r"[A-Z0-9][A-Z0-9_]{1,31}", reason) is None:
            raise InvalidProductionValueError(
                "reason_code must contain 2 to 32 canonical characters."
            )
        object.__setattr__(self, "reason_code", reason)
        if self.notes is not None:
            notes = " ".join(self.notes.split())
            if not 3 <= len(notes) <= 500:
                raise InvalidProductionValueError(
                    "scrap notes must contain 3 to 500 characters."
                )
            object.__setattr__(self, "notes", notes)


@dataclass(frozen=True, slots=True)
class StartShopFloorOperation:
    company_id: UUID
    production_order_id: UUID
    operation_sequence: int
    work_center_code: str
    expected_version: int
    occurred_at: datetime
    request_id: UUID
    correlation_id: UUID

    def __post_init__(self) -> None:
        _base_command(self)
        WorkCenterCode(self.work_center_code)


@dataclass(frozen=True, slots=True)
class RecordShopFloorProgress:
    company_id: UUID
    production_order_id: UUID
    operation_sequence: int
    expected_version: int
    occurred_at: datetime
    request_id: UUID
    correlation_id: UUID
    good_quantity: Decimal = Decimal("0")
    material_consumptions: tuple[MaterialConsumption, ...] = ()
    scraps: tuple[ScrapEntry, ...] = ()

    def __post_init__(self) -> None:
        _base_command(self)
        _report(self.good_quantity, self.material_consumptions, self.scraps, empty=False)


@dataclass(frozen=True, slots=True)
class CompleteShopFloorOperation:
    company_id: UUID
    production_order_id: UUID
    operation_sequence: int
    expected_version: int
    occurred_at: datetime
    request_id: UUID
    correlation_id: UUID
    good_quantity: Decimal = Decimal("0")
    material_consumptions: tuple[MaterialConsumption, ...] = ()
    scraps: tuple[ScrapEntry, ...] = ()

    def __post_init__(self) -> None:
        _base_command(self)
        _report(self.good_quantity, self.material_consumptions, self.scraps, empty=True)


@dataclass(frozen=True, slots=True)
class ShopFloorOperationLog:
    id: UUID
    company_id: UUID
    production_order_id: UUID
    operation_sequence: int
    event_type: ShopFloorEventType
    work_center_code: str
    good_quantity: Decimal
    material_consumptions: tuple[MaterialConsumption, ...]
    occurred_at: datetime
    actor_id: UUID
    order_version_before: int
    order_version_after: int
    request_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class ShopFloorExecutionResult:
    production_order: ProductionOrder
    operation_log_id: UUID
    inventory_transaction_id: UUID | None = None
    reservation_released: bool = False


class ProductionOrderExecutionStore(Protocol):
    async def get(self, order_id: UUID) -> ProductionOrder | None: ...

    async def save(
        self,
        aggregate: ProductionOrder,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> ProductionOrder: ...


class ShopFloorWorkCenterDirectory(Protocol):
    async def get_work_center(self, code: WorkCenterCode) -> WorkCenter | None: ...


class ShopFloorExecutionLogStore(Protocol):
    async def append(
        self,
        log: ShopFloorOperationLog,
        scraps: tuple[ScrapEntry, ...],
    ) -> None: ...

    async def totals(
        self,
        production_order_id: UUID,
        operation_sequence: int,
    ) -> tuple[Decimal, Decimal]: ...


class ShopFloorExecutionService:
    """Coordinate OP state, append-only evidence and M5 consumption atomically."""

    def __init__(
        self,
        *,
        production_orders: ProductionOrderExecutionStore,
        work_centers: ShopFloorWorkCenterDirectory,
        logs: ShopFloorExecutionLogStore,
        inventory: ProductionMaterialConsumptionGateway,
        events: ProductionEventPublisher,
    ) -> None:
        self._orders = production_orders
        self._centers = work_centers
        self._logs = logs
        self._inventory = inventory
        self._events = events

    async def start(
        self, command: StartShopFloorOperation, *, actor_id: UUID
    ) -> ShopFloorExecutionResult:
        _uuid(actor_id, "actor_id")
        order = await self._order(command.company_id, command.production_order_id)
        self._expected(order, command.expected_version)
        center = await self._centers.get_work_center(
            WorkCenterCode(command.work_center_code)
        )
        if center is None or center.company_id != command.company_id:
            raise ProductionConflictError("Work center was not found in this company.")
        changed = order.start_operation(
            command.operation_sequence,
            work_center=center,
            actor_id=actor_id,
            occurred_at=command.occurred_at,
        )
        await self._orders.save(
            changed, actor_id=actor_id, expected_version=order.record_version
        )
        log = _log(
            command,
            ShopFloorEventType.STARTED,
            center.code.value,
            Decimal("0"),
            (),
            actor_id,
            order.record_version,
            changed.record_version,
        )
        await self._logs.append(log, ())
        return ShopFloorExecutionResult(changed, log.id)

    async def report(
        self, command: RecordShopFloorProgress, *, actor_id: UUID
    ) -> ShopFloorExecutionResult:
        return await self._record(command, actor_id=actor_id, complete=False)

    async def complete(
        self, command: CompleteShopFloorOperation, *, actor_id: UUID
    ) -> ShopFloorExecutionResult:
        return await self._record(command, actor_id=actor_id, complete=True)

    async def _record(
        self,
        command: RecordShopFloorProgress | CompleteShopFloorOperation,
        *,
        actor_id: UUID,
        complete: bool,
    ) -> ShopFloorExecutionResult:
        _uuid(actor_id, "actor_id")
        order = await self._order(command.company_id, command.production_order_id)
        self._expected(order, command.expected_version)
        operation = next(
            (value for value in order.operations if value.sequence == command.operation_sequence),
            None,
        )
        if operation is None or operation.status is not ProductionOperationStatus.IN_PROGRESS:
            raise ProductionConflictError("The production operation is not in progress.")
        if operation.assigned_work_center is None:
            raise ProductionConflictError("The production operation has no work center.")
        good_before, _ = await self._logs.totals(order.id, command.operation_sequence)
        if good_before + command.good_quantity > order.planned_quantity.amount:
            raise ProductionConflictError(
                "Reported good quantity exceeds the production order quantity."
            )
        is_last = operation.sequence == order.operations[-1].sequence
        inventory_result = None
        if command.material_consumptions or (complete and is_last):
            inventory_result = await self._inventory.consume_production_materials(
                ConsumeProductionMaterialsContract(
                    company_id=command.company_id,
                    production_order_id=command.production_order_id,
                    lines=tuple(
                        ProductionMaterialConsumptionLineContract(
                            value.product_id, value.quantity
                        )
                        for value in command.material_consumptions
                    ),
                    finalize_reservation=complete and is_last,
                    request_id=command.request_id,
                    correlation_id=command.correlation_id,
                ),
                actor_id,
            )
        changed = order
        if inventory_result is not None:
            for trace in inventory_result.traces:
                plan = next(
                    (value for value in changed.materials if value.product_id == trace.product_id),
                    None,
                )
                if plan is None:
                    raise ProductionConflictError(
                        "Consumed inventory is not planned for this production order."
                    )
                before = changed.record_version
                changed = changed.record_consumption(
                    ProductionLotTrace(
                        lot_id=trace.lot_id,
                        product_id=trace.product_id,
                        quantity=ProductionQuantity(
                            trace.quantity, plan.planned_quantity.unit
                        ),
                    )
                )
                await self._orders.save(
                    changed, actor_id=actor_id, expected_version=before
                )
        if complete:
            before = changed.record_version
            changed = changed.complete_operation(
                command.operation_sequence,
                actor_id=actor_id,
                occurred_at=command.occurred_at,
            )
            await self._orders.save(changed, actor_id=actor_id, expected_version=before)
            if good_before + command.good_quantity <= 0:
                raise ProductionConflictError(
                    "An operation requires positive good production before completion."
                )
        log = _log(
            command,
            ShopFloorEventType.COMPLETED if complete else ShopFloorEventType.PROGRESS,
            operation.assigned_work_center.code.value,
            command.good_quantity,
            command.material_consumptions,
            actor_id,
            order.record_version,
            changed.record_version,
        )
        await self._logs.append(log, command.scraps)
        await self._publish_execution_events(
            command,
            changed,
            inventory_transaction_id=(
                None if inventory_result is None else inventory_result.transaction_id
            ),
            reservation_released=(
                False if inventory_result is None else inventory_result.reservation_released
            ),
            complete=complete,
        )
        return ShopFloorExecutionResult(
            changed,
            log.id,
            None if inventory_result is None else inventory_result.transaction_id,
            False if inventory_result is None else inventory_result.reservation_released,
        )

    async def _publish_execution_events(
        self,
        command: RecordShopFloorProgress | CompleteShopFloorOperation,
        order: ProductionOrder,
        *,
        inventory_transaction_id: UUID | None,
        reservation_released: bool,
        complete: bool,
    ) -> None:
        common = {
            "operation_sequence": command.operation_sequence,
            "good_quantity": str(command.good_quantity),
        }
        if command.material_consumptions:
            await self._events.publish(
                _execution_event(
                    command,
                    order,
                    ProductionEventType.MATERIAL_CONSUMED,
                    {
                        **common,
                        "inventory_transaction_id": (
                            None
                            if inventory_transaction_id is None
                            else str(inventory_transaction_id)
                        ),
                        "reservation_released": reservation_released,
                        "materials": [
                            {
                                "product_id": str(value.product_id),
                                "quantity": str(value.quantity),
                            }
                            for value in command.material_consumptions
                        ],
                    },
                )
            )
        if command.scraps:
            await self._events.publish(
                _execution_event(
                    command,
                    order,
                    ProductionEventType.SCRAP_RECORDED,
                    {
                        **common,
                        "scraps": [
                            {
                                "product_id": str(value.product_id),
                                "quantity": str(value.quantity),
                                "reason_code": value.reason_code,
                                "notes": value.notes,
                            }
                            for value in command.scraps
                        ],
                    },
                )
            )
        if complete:
            await self._events.publish(
                _execution_event(
                    command,
                    order,
                    ProductionEventType.OPERATION_COMPLETED,
                    {**common, "reservation_released": reservation_released},
                )
            )

    async def _order(self, company_id: UUID, order_id: UUID) -> ProductionOrder:
        order = await self._orders.get(order_id)
        if order is None or order.company_id != company_id:
            raise ProductionConflictError("Production order was not found in this company.")
        return order

    @staticmethod
    def _expected(order: ProductionOrder, expected_version: int) -> None:
        if order.record_version != expected_version:
            raise ProductionVersionConflictError(expected_version)


def _log(
    command: StartShopFloorOperation | RecordShopFloorProgress | CompleteShopFloorOperation,
    event_type: ShopFloorEventType,
    work_center_code: str,
    good_quantity: Decimal,
    materials: tuple[MaterialConsumption, ...],
    actor_id: UUID,
    version_before: int,
    version_after: int,
) -> ShopFloorOperationLog:
    return ShopFloorOperationLog(
        uuid4(),
        command.company_id,
        command.production_order_id,
        command.operation_sequence,
        event_type,
        work_center_code,
        good_quantity,
        materials,
        command.occurred_at,
        actor_id,
        version_before,
        version_after,
        command.request_id,
        command.correlation_id,
    )


def _execution_event(
    command: RecordShopFloorProgress | CompleteShopFloorOperation,
    order: ProductionOrder,
    event_type: ProductionEventType,
    payload: dict[str, Any],
) -> ProductionDomainEvent:
    return ProductionDomainEvent(
        event_type=event_type,
        company_id=command.company_id,
        production_order_id=command.production_order_id,
        aggregate_version=order.record_version,
        occurred_at=command.occurred_at,
        request_id=command.request_id,
        correlation_id=command.correlation_id,
        causation_id=None,
        payload=payload,
    )


def _base_command(
    value: StartShopFloorOperation
    | RecordShopFloorProgress
    | CompleteShopFloorOperation,
) -> None:
    for field in ("company_id", "production_order_id", "request_id", "correlation_id"):
        _uuid(getattr(value, field), field)
    if type(value.operation_sequence) is not int or value.operation_sequence < 1:
        raise InvalidProductionValueError("operation_sequence must be positive.")
    if type(value.expected_version) is not int or value.expected_version < 1:
        raise InvalidProductionValueError("expected_version must be positive.")
    occurred_at = value.occurred_at
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise InvalidProductionValueError("occurred_at must be timezone-aware.")


def _report(
    good: Decimal,
    materials: tuple[MaterialConsumption, ...],
    scraps: tuple[ScrapEntry, ...],
    *,
    empty: bool,
) -> None:
    _non_negative_decimal(good, "good_quantity")
    if not isinstance(materials, tuple) or any(
        not isinstance(value, MaterialConsumption) for value in materials
    ):
        raise InvalidProductionValueError("material_consumptions are invalid.")
    if not isinstance(scraps, tuple) or any(
        not isinstance(value, ScrapEntry) for value in scraps
    ):
        raise InvalidProductionValueError("scraps are invalid.")
    product_ids = tuple(value.product_id for value in materials)
    if len(product_ids) != len(set(product_ids)):
        raise InvalidProductionValueError("material products must be unique per report.")
    if not empty and good == 0 and not materials and not scraps:
        raise InvalidProductionValueError("A progress report cannot be empty.")


def _uuid(value: object, field: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidProductionValueError(f"{field} must be a non-zero UUID.")


def _positive_decimal(value: Decimal, field: str) -> None:
    _non_negative_decimal(value, field)
    if value == 0:
        raise InvalidProductionValueError(f"{field} must be positive.")


def _non_negative_decimal(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise InvalidProductionValueError(f"{field} must be a non-negative Decimal.")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -6:
        raise InvalidProductionValueError(f"{field} supports at most six decimal places.")


__all__ = [
    "CompleteShopFloorOperation",
    "MaterialConsumption",
    "RecordShopFloorProgress",
    "ScrapEntry",
    "ShopFloorEventType",
    "ShopFloorExecutionLogStore",
    "ShopFloorExecutionResult",
    "ShopFloorExecutionService",
    "ShopFloorOperationLog",
    "ShopFloorWorkCenterDirectory",
    "StartShopFloorOperation",
]

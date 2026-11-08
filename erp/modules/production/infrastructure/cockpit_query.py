"""PostgreSQL read model for the Production cockpit."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.application.cockpit import (
    ProductionCockpitAlert,
    ProductionCockpitOrder,
    ProductionCockpitSnapshot,
    ProductionWorkCenterLoad,
)
from erp.modules.production.infrastructure.engineering_model import (
    RoutingHeaderModel,
    RoutingOperationModel,
    WorkCenterModel,
)
from erp.modules.production.infrastructure.production_event_model import (
    ProductionSynchronizationRequestModel,
)
from erp.modules.production.infrastructure.production_event_state import (
    PRODUCTION_SYNCHRONIZATION_REQUESTED,
)
from erp.modules.production.infrastructure.production_order_model import (
    ProductionOrderModel,
    ProductionOrderOperationExecutionModel,
)
from erp.modules.production.infrastructure.shop_floor_model import (
    ScrapRecordModel,
    ShopFloorOperationLogModel,
)
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel

STANDARD_SHIFT_MINUTES = 480
_ACTIVE_STATUSES = ("DRAFT", "RELEASED", "IN_PROGRESS")


class PostgresProductionCockpitReader:
    """Build one consistent tenant snapshot from Production read models."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> ProductionCockpitSnapshot:
        async with self._database.session() as session:
            orders = tuple(
                await session.scalars(
                    select(ProductionOrderModel)
                    .where(
                        ProductionOrderModel.company_id == company_id,
                        ProductionOrderModel.status.in_(_ACTIVE_STATUSES),
                    )
                    .order_by(
                        ProductionOrderModel.due_on,
                        ProductionOrderModel.order_number,
                    )
                    .limit(limit)
                )
            )
            order_ids = tuple(value.id for value in orders)
            centers = tuple(
                await session.scalars(
                    select(WorkCenterModel)
                    .where(WorkCenterModel.company_id == company_id)
                    .order_by(WorkCenterModel.code)
                )
            )
            if not order_ids:
                empty_loads = tuple(_empty_center(value) for value in centers)
                return ProductionCockpitSnapshot(
                    company_id,
                    as_of,
                    STANDARD_SHIFT_MINUTES,
                    (),
                    empty_loads,
                    (),
                    await _pending_count(session, company_id),
                )

            operation_rows = tuple(
                (
                    operation,
                    setup or Decimal("0"),
                    run or Decimal("0"),
                )
                for operation, setup, run in (
                    await session.execute(
                        select(
                            ProductionOrderOperationExecutionModel,
                            RoutingOperationModel.setup_minutes,
                            RoutingOperationModel.run_minutes_per_unit,
                        )
                        .join(
                            ProductionOrderModel,
                            (
                                ProductionOrderModel.company_id
                                == ProductionOrderOperationExecutionModel.company_id
                            )
                            & (
                                ProductionOrderModel.id
                                == ProductionOrderOperationExecutionModel.production_order_id
                            ),
                        )
                        .outerjoin(
                            RoutingHeaderModel,
                            (RoutingHeaderModel.company_id == ProductionOrderModel.company_id)
                            & (RoutingHeaderModel.product_id == ProductionOrderModel.product_id)
                            & (
                                RoutingHeaderModel.version_code
                                == ProductionOrderModel.routing_version_code
                            ),
                        )
                        .outerjoin(
                            RoutingOperationModel,
                            (RoutingOperationModel.company_id == RoutingHeaderModel.company_id)
                            & (RoutingOperationModel.routing_id == RoutingHeaderModel.id)
                            & (
                                RoutingOperationModel.sequence
                                == ProductionOrderOperationExecutionModel.sequence
                            ),
                        )
                        .where(
                            ProductionOrderOperationExecutionModel.company_id == company_id,
                            ProductionOrderOperationExecutionModel.production_order_id.in_(
                                order_ids
                            ),
                        )
                        .order_by(
                            ProductionOrderOperationExecutionModel.production_order_id,
                            ProductionOrderOperationExecutionModel.sequence,
                        )
                    )
                ).all()
            )
            good_rows = (
                await session.execute(
                    select(
                        ShopFloorOperationLogModel.production_order_id,
                        func.coalesce(func.sum(ShopFloorOperationLogModel.good_quantity), 0),
                    )
                    .where(
                        ShopFloorOperationLogModel.company_id == company_id,
                        ShopFloorOperationLogModel.production_order_id.in_(order_ids),
                    )
                    .group_by(ShopFloorOperationLogModel.production_order_id)
                )
            ).all()
            good_by_order: dict[UUID, Decimal] = {
                order_id: Decimal(value) for order_id, value in good_rows
            }
            scrap_rows = (
                await session.execute(
                    select(
                        ScrapRecordModel.production_order_id,
                        func.coalesce(func.sum(ScrapRecordModel.quantity), 0),
                    )
                    .where(
                        ScrapRecordModel.company_id == company_id,
                        ScrapRecordModel.production_order_id.in_(order_ids),
                    )
                    .group_by(ScrapRecordModel.production_order_id)
                )
            ).all()
            scrap_by_order: dict[UUID, Decimal] = {
                order_id: Decimal(value) for order_id, value in scrap_rows
            }
            pending_ids = set(
                await session.scalars(
                    select(ProductionSynchronizationRequestModel.production_order_id).where(
                        ProductionSynchronizationRequestModel.company_id == company_id,
                        ProductionSynchronizationRequestModel.production_order_id.in_(order_ids),
                    )
                )
            )
            synchronization_rows = (
                await session.execute(
                    select(
                        OutboxEventModel.aggregate_id,
                        func.max(OutboxEventModel.occurred_at),
                    )
                    .where(
                        OutboxEventModel.source_module == "production",
                        OutboxEventModel.event_type == PRODUCTION_SYNCHRONIZATION_REQUESTED,
                        OutboxEventModel.aggregate_id.in_(order_ids),
                    )
                    .group_by(OutboxEventModel.aggregate_id)
                )
            ).all()
            synchronized_at: dict[UUID, datetime] = {}
            for order_id, value in synchronization_rows:
                synchronized_at[order_id] = value
            pending_total = await _pending_count(session, company_id)

        operations_by_order: dict[
            UUID,
            list[tuple[ProductionOrderOperationExecutionModel, Decimal, Decimal]],
        ] = defaultdict(list)
        for operation, setup, run in operation_rows:
            operations_by_order[operation.production_order_id].append((operation, setup, run))

        center_load: dict[str, list[Decimal | int]] = {
            value.code: [Decimal("0"), 0] for value in centers
        }
        order_rows: list[ProductionCockpitOrder] = []
        alerts: list[ProductionCockpitAlert] = []
        for order in orders:
            operations = operations_by_order.get(order.id, [])
            completed = sum(1 for value, _, _ in operations if value.status == "COMPLETED")
            current = next(
                (value for value, _, _ in operations if value.status == "IN_PROGRESS"),
                next((value for value, _, _ in operations if value.status == "PENDING"), None),
            )
            good = Decimal(good_by_order.get(order.id, 0))
            scrap = Decimal(scrap_by_order.get(order.id, 0))
            operation_progress = (
                Decimal(completed * 100) / Decimal(len(operations)) if operations else Decimal("0")
            )
            quantity_progress = good * Decimal("100") / order.planned_quantity
            progress = min(max(operation_progress, quantity_progress), Decimal("100"))
            for operation, setup, run in operations:
                if operation.status == "COMPLETED":
                    continue
                center_code = operation.assigned_work_center_code or next(
                    iter(operation.allowed_work_centers), None
                )
                if center_code is None:
                    continue
                bucket = center_load.setdefault(center_code, [Decimal("0"), 0])
                bucket[0] = Decimal(bucket[0]) + setup + run * order.planned_quantity
                bucket[1] = int(bucket[1]) + 1
            if order.due_on < as_of.date():
                alerts.append(
                    ProductionCockpitAlert(
                        "CRITICAL",
                        "OVERDUE_ORDER",
                        f"OP {order.order_number} vencida",
                        f"Prazo industrial expirou em {order.due_on:%d/%m/%Y}.",
                        production_order_id=order.id,
                    )
                )
            if order.id in pending_ids:
                alerts.append(
                    ProductionCockpitAlert(
                        "WARNING",
                        "SYNCHRONIZATION_PENDING",
                        f"OP {order.order_number} aguardando reavaliação",
                        "Uma mudança de estoque ou engenharia ainda está na fila durável.",
                        production_order_id=order.id,
                    )
                )
            if scrap > 0:
                alerts.append(
                    ProductionCockpitAlert(
                        "WARNING",
                        "SCRAP_RECORDED",
                        f"Refugo apontado na OP {order.order_number}",
                        f"Quantidade acumulada: {scrap.normalize()}.",
                        production_order_id=order.id,
                    )
                )
            order_rows.append(
                ProductionCockpitOrder(
                    order.id,
                    order.order_number,
                    order.product_id,
                    order.status,
                    order.planned_quantity,
                    order.planned_uom,
                    good,
                    scrap,
                    progress.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                    completed,
                    len(operations),
                    None if current is None else current.name,
                    None if current is None else current.assigned_work_center_code,
                    order.planned_start_on,
                    order.due_on,
                    order.id in pending_ids,
                    synchronized_at.get(order.id),
                )
            )

        center_by_code = {value.code: value for value in centers}
        work_center_loads: list[ProductionWorkCenterLoad] = []
        for code in sorted(set(center_by_code) | set(center_load)):
            planned, active = center_load.get(code, [Decimal("0"), 0])
            percent = Decimal(planned) * Decimal("100") / STANDARD_SHIFT_MINUTES
            state = "BOTTLENECK" if percent >= 100 else "ATTENTION" if percent >= 85 else "NORMAL"
            center = center_by_code.get(code)
            work_center_loads.append(
                ProductionWorkCenterLoad(
                    code,
                    () if center is None else tuple(center.capabilities),
                    Decimal(planned).quantize(Decimal("0.1")),
                    Decimal(STANDARD_SHIFT_MINUTES),
                    percent.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                    int(active),
                    state,
                )
            )
            if state != "NORMAL":
                alerts.append(
                    ProductionCockpitAlert(
                        "CRITICAL" if state == "BOTTLENECK" else "WARNING",
                        "WORK_CENTER_LOAD",
                        f"Carga elevada em {code}",
                        f"Ocupação projetada de {percent.quantize(Decimal('0.1'))}% do turno padrão.",
                        work_center_code=code,
                    )
                )
        alerts.sort(key=lambda value: (value.severity != "CRITICAL", value.title))
        return ProductionCockpitSnapshot(
            company_id,
            as_of,
            STANDARD_SHIFT_MINUTES,
            tuple(order_rows),
            tuple(work_center_loads),
            tuple(alerts),
            pending_total,
        )


async def _pending_count(session: AsyncSession, company_id: UUID) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(ProductionSynchronizationRequestModel)
        .where(ProductionSynchronizationRequestModel.company_id == company_id)
    )
    return int(result or 0)


def _empty_center(center: WorkCenterModel) -> ProductionWorkCenterLoad:
    return ProductionWorkCenterLoad(
        center.code,
        tuple(center.capabilities),
        Decimal("0"),
        Decimal(STANDARD_SHIFT_MINUTES),
        Decimal("0"),
        0,
        "NORMAL",
    )


__all__ = ["STANDARD_SHIFT_MINUTES", "PostgresProductionCockpitReader"]

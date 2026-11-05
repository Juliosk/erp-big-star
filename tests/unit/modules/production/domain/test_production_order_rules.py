"""Pure Production Order lifecycle and manufacturing invariant tests."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    EngineeringUnavailableError,
    EngineeringVersion,
    InvalidProductionOrderStateError,
    InvalidProductionValueError,
    LotTraceabilityError,
    MaterialRequirement,
    ProductionEngineeringSnapshot,
    ProductionLotTrace,
    ProductionMaterialPlan,
    ProductionOperationStatus,
    ProductionOrder,
    ProductionOrderOperation,
    ProductionOrderStatus,
    ProductionQuantity,
    ProductionQuantityExceededError,
    ProductionRouting,
    ProductionScopeError,
    RoutingConsistencyError,
    RoutingOperation,
    ScrapRate,
    UnitOfMeasure,
    UnitOfMeasureMismatchError,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)

CREATED_AT = datetime(2026, 11, 5, 9, tzinfo=UTC)
PLANNED_START = date(2026, 11, 6)
DUE_ON = date(2026, 11, 10)


def quantity(value: str, unit: UnitOfMeasure = UnitOfMeasure.EACH) -> ProductionQuantity:
    return ProductionQuantity(Decimal(value), unit)


def engineering_version(code: str = "R1") -> EngineeringVersion:
    return EngineeringVersion(
        code=code,
        revision=1,
        effective_from=date(2026, 11, 1),
        effective_until=date(2026, 12, 31),
    )


def engineering(
    *,
    company_id: UUID,
    product_id: UUID,
    raw_material_id: UUID,
    bom_record_version: int = 1,
    routing_record_version: int = 1,
) -> tuple[BillOfMaterials, ProductionRouting]:
    bom = BillOfMaterials(
        company_id=company_id,
        product_id=product_id,
        version=engineering_version(),
        output_quantity=quantity("1"),
        items=(
            BomItem(
                raw_material_id,
                quantity("2", UnitOfMeasure.KILOGRAM),
                ScrapRate(),
            ),
        ),
        record_version=bom_record_version,
    )
    routing = ProductionRouting(
        company_id=company_id,
        product_id=product_id,
        version=engineering_version(),
        operations=(
            RoutingOperation(
                10,
                "Cut",
                WorkCenterConstraint(
                    company_id,
                    (WorkCenterCode("CUT-01"),),
                    frozenset({"LASER"}),
                ),
                Decimal("5"),
                Decimal("1"),
            ),
            RoutingOperation(
                20,
                "Assembly",
                WorkCenterConstraint(
                    company_id,
                    (WorkCenterCode("ASM-01"),),
                    frozenset({"ASSEMBLY"}),
                ),
                Decimal("3"),
                Decimal("2"),
            ),
        ),
        record_version=routing_record_version,
    )
    return bom, routing


def draft_order() -> tuple[ProductionOrder, BillOfMaterials, ProductionRouting, UUID]:
    company_id, product_id, raw_material_id = uuid4(), uuid4(), uuid4()
    bom, routing = engineering(
        company_id=company_id,
        product_id=product_id,
        raw_material_id=raw_material_id,
    )
    order = ProductionOrder.create(
        company_id=company_id,
        order_number=" op-0001 ",
        product_id=product_id,
        planned_quantity=quantity("5"),
        planned_start_on=PLANNED_START,
        due_on=DUE_ON,
        bom=bom,
        routing=routing,
        material_requirements=(
            MaterialRequirement(
                raw_material_id,
                quantity("10", UnitOfMeasure.KILOGRAM),
            ),
        ),
        engineering_approved_at=CREATED_AT,
        engineering_approved_by=uuid4(),
        created_at=CREATED_AT,
        created_by=uuid4(),
    )
    return order, bom, routing, raw_material_id


def center(order: ProductionOrder, code: str, capability: str) -> WorkCenter:
    return WorkCenter(
        order.company_id,
        WorkCenterCode(code),
        frozenset({capability}),
    )


def release(order: ProductionOrder, bom: BillOfMaterials, routing: ProductionRouting) -> ProductionOrder:
    return order.release(
        bom=bom,
        routing=routing,
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=1),
    )


def start_first(
    order: ProductionOrder,
    bom: BillOfMaterials,
    routing: ProductionRouting,
) -> ProductionOrder:
    released = release(order, bom, routing)
    return released.start_operation(
        10,
        work_center=center(order, "CUT-01", "LASER"),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=2),
    )


def ready_to_complete(
    order: ProductionOrder,
    bom: BillOfMaterials,
    routing: ProductionRouting,
    raw_material_id: UUID,
) -> ProductionOrder:
    current = start_first(order, bom, routing)
    current = current.record_consumption(
        ProductionLotTrace(
            uuid4(),
            raw_material_id,
            quantity("10", UnitOfMeasure.KILOGRAM),
        )
    )
    current = current.complete_operation(
        10, actor_id=uuid4(), occurred_at=CREATED_AT + timedelta(hours=3)
    )
    current = current.start_operation(
        20,
        work_center=center(order, "ASM-01", "ASSEMBLY"),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=4),
    )
    return current.complete_operation(
        20, actor_id=uuid4(), occurred_at=CREATED_AT + timedelta(hours=5)
    )


def test_complete_manufacturing_lifecycle_tracks_lots_and_variance() -> None:
    order, bom, routing, raw_material_id = draft_order()
    released = release(order, bom, routing)
    in_progress = released.start_operation(
        10,
        work_center=center(order, "CUT-01", "LASER"),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=2),
    )
    lot_id = uuid4()
    in_progress = in_progress.record_consumption(
        ProductionLotTrace(
            lot_id,
            raw_material_id,
            quantity("6", UnitOfMeasure.KILOGRAM),
        )
    )
    in_progress = in_progress.record_consumption(
        ProductionLotTrace(
            lot_id,
            raw_material_id,
            quantity("4", UnitOfMeasure.KILOGRAM),
        )
    )
    in_progress = in_progress.complete_operation(
        10,
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=3),
    )
    in_progress = in_progress.start_operation(
        20,
        work_center=center(order, "ASM-01", "ASSEMBLY"),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=4),
    )
    in_progress = in_progress.complete_operation(
        20,
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=5),
    )
    completed = in_progress.complete(
        output_lots=(
            ProductionLotTrace(uuid4(), order.product_id, quantity("4.5")),
        ),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=6),
    )

    assert order.order_number == "OP-0001"
    assert order.status is ProductionOrderStatus.DRAFT
    assert released.status is ProductionOrderStatus.RELEASED
    assert completed.status is ProductionOrderStatus.COMPLETED
    assert completed.materials[0].actual_amount == Decimal("10.000000")
    assert len(completed.materials[0].consumptions) == 1
    assert completed.actual_output_amount == Decimal("4.500000")
    assert completed.output_variance == Decimal("-0.500000")
    assert completed.record_version == 9
    with pytest.raises(FrozenInstanceError):
        completed.status = ProductionOrderStatus.CANCELLED  # type: ignore[misc]


def test_release_revalidates_exact_approved_engineering_versions() -> None:
    order, bom, routing, _ = draft_order()

    with pytest.raises(EngineeringUnavailableError):
        order.release(
            bom=replace(bom, record_version=2),
            routing=routing,
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=1),
        )
    with pytest.raises(EngineeringUnavailableError):
        order.release(
            bom=bom,
            routing=replace(routing, record_version=2),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=1),
        )


def test_engineering_must_be_effective_and_own_the_same_tenant_product() -> None:
    company_id, product_id, raw_material_id = uuid4(), uuid4(), uuid4()
    bom, routing = engineering(
        company_id=company_id,
        product_id=product_id,
        raw_material_id=raw_material_id,
    )
    future_bom = replace(
        bom,
        version=EngineeringVersion("R2", 2, date(2027, 1, 1)),
    )
    with pytest.raises(EngineeringUnavailableError):
        ProductionEngineeringSnapshot.capture(
            bom=future_bom,
            routing=routing,
            approved_at=CREATED_AT,
            approved_by=uuid4(),
            planned_start_on=PLANNED_START,
        )
    with pytest.raises(RoutingConsistencyError):
        ProductionEngineeringSnapshot.capture(
            bom=bom,
            routing=replace(routing, product_id=uuid4()),
            approved_at=CREATED_AT,
            approved_by=uuid4(),
            planned_start_on=PLANNED_START,
        )


def test_routing_sequence_and_work_center_constraints_are_strict() -> None:
    order, bom, routing, _ = draft_order()
    released = release(order, bom, routing)

    with pytest.raises(RoutingConsistencyError, match="approved sequence"):
        released.start_operation(
            20,
            work_center=center(order, "ASM-01", "ASSEMBLY"),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=2),
        )
    with pytest.raises(RoutingConsistencyError, match="does not satisfy"):
        released.start_operation(
            10,
            work_center=center(order, "CUT-01", "MANUAL"),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=2),
        )
    with pytest.raises(RoutingConsistencyError, match="outside"):
        released.start_operation(
            99,
            work_center=center(order, "CUT-01", "LASER"),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=2),
        )
    in_progress = released.start_operation(
        10,
        work_center=center(order, "CUT-01", "LASER"),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=2),
    )
    with pytest.raises(RoutingConsistencyError, match="already in progress"):
        in_progress.start_operation(
            10,
            work_center=center(order, "CUT-01", "LASER"),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=3),
        )


def test_material_consumption_enforces_plan_unit_and_lot_traceability() -> None:
    order, bom, routing, raw_material_id = draft_order()
    in_progress = start_first(order, bom, routing)

    with pytest.raises(LotTraceabilityError, match="not planned"):
        in_progress.record_consumption(
            ProductionLotTrace(uuid4(), uuid4(), quantity("1"))
        )
    with pytest.raises(UnitOfMeasureMismatchError):
        in_progress.record_consumption(
            ProductionLotTrace(uuid4(), raw_material_id, quantity("1"))
        )
    with pytest.raises(ProductionQuantityExceededError):
        in_progress.record_consumption(
            ProductionLotTrace(
                uuid4(),
                raw_material_id,
                quantity("11", UnitOfMeasure.KILOGRAM),
            )
        )


def test_completion_requires_route_consumption_and_valid_output_lots() -> None:
    order, bom, routing, raw_material_id = draft_order()
    in_progress = start_first(order, bom, routing)

    with pytest.raises(RoutingConsistencyError, match="all approved"):
        in_progress.complete(
            output_lots=(ProductionLotTrace(uuid4(), order.product_id, quantity("1")),),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=3),
        )
    first_completed = in_progress.complete_operation(
        10, actor_id=uuid4(), occurred_at=CREATED_AT + timedelta(hours=3)
    )
    second_started = first_completed.start_operation(
        20,
        work_center=center(order, "ASM-01", "ASSEMBLY"),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=4),
    )
    routed = second_started.complete_operation(
        20, actor_id=uuid4(), occurred_at=CREATED_AT + timedelta(hours=5)
    )
    with pytest.raises(LotTraceabilityError, match="planned material"):
        routed.complete(
            output_lots=(ProductionLotTrace(uuid4(), order.product_id, quantity("1")),),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )
    consumed = routed.record_consumption(
        ProductionLotTrace(
            uuid4(),
            raw_material_id,
            quantity("10", UnitOfMeasure.KILOGRAM),
        )
    )
    with pytest.raises(ProductionQuantityExceededError):
        consumed.complete(
            output_lots=(ProductionLotTrace(uuid4(), order.product_id, quantity("6")),),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )
    with pytest.raises(LotTraceabilityError, match="output lot"):
        consumed.complete(
            output_lots=(),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )


def test_cancellation_and_rescheduling_are_blocked_after_execution_starts() -> None:
    order, bom, routing, _ = draft_order()
    rescheduled = order.reschedule(
        planned_start_on=date(2026, 11, 7),
        due_on=date(2026, 11, 12),
    )
    assert rescheduled.planned_quantity == quantity("5")
    cancelled = order.cancel(
        reason="  Planejamento cancelado  ",
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=1),
    )
    assert cancelled.status is ProductionOrderStatus.CANCELLED
    assert cancelled.cancellation_reason == "Planejamento cancelado"

    in_progress = start_first(order, bom, routing)
    with pytest.raises(InvalidProductionOrderStateError):
        in_progress.reschedule(
            planned_start_on=PLANNED_START,
            due_on=DUE_ON,
        )


def test_creation_contract_rejects_scope_unit_and_material_errors() -> None:
    order, bom, routing, raw_material_id = draft_order()
    base: dict[str, Any] = {
        "company_id": order.company_id,
        "order_number": "OP-INVALID",
        "product_id": order.product_id,
        "planned_quantity": quantity("5"),
        "planned_start_on": PLANNED_START,
        "due_on": DUE_ON,
        "bom": bom,
        "routing": routing,
        "material_requirements": (
            MaterialRequirement(
                raw_material_id,
                quantity("10", UnitOfMeasure.KILOGRAM),
            ),
        ),
        "engineering_approved_at": CREATED_AT,
        "engineering_approved_by": uuid4(),
        "created_at": CREATED_AT,
        "created_by": uuid4(),
    }
    with pytest.raises(ProductionScopeError):
        ProductionOrder.create(**{**base, "company_id": uuid4()})
    with pytest.raises(UnitOfMeasureMismatchError):
        ProductionOrder.create(
            **{
                **base,
                "planned_quantity": quantity("5", UnitOfMeasure.KILOGRAM),
            }
        )
    with pytest.raises(InvalidProductionValueError, match="non-empty"):
        ProductionOrder.create(**{**base, "material_requirements": ()})
    with pytest.raises(InvalidProductionValueError, match="MaterialRequirement"):
        ProductionOrder.create(
            **{**base, "material_requirements": cast(Any, ("bad",))}
        )
    with pytest.raises(InvalidProductionValueError, match="order_number must be text"):
        ProductionOrder.create(**{**base, "order_number": cast(Any, 123)})


def test_rescheduling_enforces_dates_and_engineering_effectivity() -> None:
    order, _, _, _ = draft_order()

    with pytest.raises(InvalidProductionValueError, match="cannot precede"):
        order.reschedule(
            planned_start_on=date(2026, 11, 8),
            due_on=date(2026, 11, 7),
        )
    with pytest.raises(EngineeringUnavailableError):
        order.reschedule(
            planned_start_on=date(2027, 1, 1),
            due_on=date(2027, 1, 2),
        )


def test_cancellation_reason_and_transition_timestamp_are_validated() -> None:
    order, bom, routing, _ = draft_order()

    with pytest.raises(InvalidProductionValueError, match="must be text"):
        order.cancel(
            reason=cast(Any, 123),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=1),
        )
    with pytest.raises(InvalidProductionValueError, match="between 3"):
        order.cancel(
            reason="x",
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=1),
        )
    with pytest.raises(InvalidProductionValueError, match="cannot precede"):
        order.release(
            bom=bom,
            routing=routing,
            actor_id=uuid4(),
            occurred_at=CREATED_AT - timedelta(seconds=1),
        )


def test_output_lot_contract_rejects_wrong_product_unit_and_duplicates() -> None:
    order, bom, routing, raw_material_id = draft_order()
    ready = ready_to_complete(order, bom, routing, raw_material_id)
    lot_id = uuid4()

    with pytest.raises(LotTraceabilityError, match="produced product"):
        ready.complete(
            output_lots=(ProductionLotTrace(lot_id, uuid4(), quantity("1")),),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )
    with pytest.raises(UnitOfMeasureMismatchError, match="planned production unit"):
        ready.complete(
            output_lots=(
                ProductionLotTrace(
                    lot_id,
                    order.product_id,
                    quantity("1", UnitOfMeasure.KILOGRAM),
                ),
            ),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )
    with pytest.raises(LotTraceabilityError, match="unique"):
        ready.complete(
            output_lots=(
                ProductionLotTrace(lot_id, order.product_id, quantity("1")),
                ProductionLotTrace(lot_id, order.product_id, quantity("1")),
            ),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )
    with pytest.raises(LotTraceabilityError, match="ProductionLotTrace"):
        ready.complete(
            output_lots=cast(Any, ("bad",)),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=6),
        )


def test_material_plan_constructor_and_consume_are_strict() -> None:
    product_id = uuid4()
    planned = quantity("2", UnitOfMeasure.KILOGRAM)
    lot_id = uuid4()
    trace = ProductionLotTrace(lot_id, product_id, quantity("1", UnitOfMeasure.KILOGRAM))

    with pytest.raises(LotTraceabilityError, match="planned product"):
        ProductionMaterialPlan(
            product_id,
            planned,
            (ProductionLotTrace(lot_id, uuid4(), trace.quantity),),
        )
    with pytest.raises(UnitOfMeasureMismatchError):
        ProductionMaterialPlan(
            product_id,
            planned,
            (ProductionLotTrace(lot_id, product_id, quantity("1", UnitOfMeasure.LITER)),),
        )
    with pytest.raises(LotTraceabilityError, match="unique"):
        ProductionMaterialPlan(product_id, planned, (trace, trace))
    with pytest.raises(ProductionQuantityExceededError):
        ProductionMaterialPlan(
            product_id,
            planned,
            (
                ProductionLotTrace(
                    lot_id,
                    product_id,
                    quantity("3", UnitOfMeasure.KILOGRAM),
                ),
            ),
        )
    plan = ProductionMaterialPlan(product_id, planned)
    with pytest.raises(InvalidProductionValueError, match="trace"):
        plan.consume(cast(Any, "bad"))
    with pytest.raises(LotTraceabilityError):
        plan.consume(ProductionLotTrace(lot_id, uuid4(), trace.quantity))
    with pytest.raises(UnitOfMeasureMismatchError):
        plan.consume(
            ProductionLotTrace(lot_id, product_id, quantity("1", UnitOfMeasure.LITER))
        )


def test_operation_execution_evidence_is_internally_consistent() -> None:
    order, _, _, _ = draft_order()
    pending = order.operations[0]
    cut_center = center(order, "CUT-01", "LASER")

    with pytest.raises(RoutingConsistencyError, match="pending operations"):
        replace(pending, assigned_work_center=cut_center)
    with pytest.raises(RoutingConsistencyError, match="require work center"):
        replace(pending, status=ProductionOperationStatus.IN_PROGRESS)
    started = pending.start(
        work_center=cut_center,
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=1),
    )
    with pytest.raises(InvalidProductionOrderStateError, match="not pending"):
        started.start(
            work_center=cut_center,
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=2),
        )
    with pytest.raises(RoutingConsistencyError, match="completion evidence"):
        replace(started, completed_at=CREATED_AT + timedelta(hours=2))
    with pytest.raises(RoutingConsistencyError, match="require completion"):
        replace(started, status=ProductionOperationStatus.COMPLETED)
    with pytest.raises(InvalidProductionOrderStateError, match="not in progress"):
        pending.complete(actor_id=uuid4(), occurred_at=CREATED_AT)
    completed = started.complete(
        actor_id=uuid4(), occurred_at=CREATED_AT + timedelta(hours=2)
    )
    with pytest.raises(RoutingConsistencyError, match="cannot precede"):
        replace(completed, completed_at=CREATED_AT)


def test_direct_lifecycle_snapshots_cannot_bypass_aggregate_transitions() -> None:
    order, bom, routing, _raw_material_id = draft_order()
    released = release(order, bom, routing)
    in_progress = start_first(order, bom, routing)
    output = (ProductionLotTrace(uuid4(), order.product_id, quantity("1")),)

    with pytest.raises(InvalidProductionOrderStateError, match="draft orders"):
        replace(order, released_at=CREATED_AT)
    with pytest.raises(RoutingConsistencyError, match="draft operations"):
        replace(order, operations=in_progress.operations)
    with pytest.raises(LotTraceabilityError, match="draft orders"):
        replace(order, output_lots=output)
    with pytest.raises(InvalidProductionOrderStateError, match="cancellation evidence"):
        replace(order, status=ProductionOrderStatus.CANCELLED)
    cancelled = order.cancel(
        reason="Cancelled by planning",
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=1),
    )
    with pytest.raises(LotTraceabilityError, match="cancelled orders"):
        replace(cancelled, output_lots=output)
    with pytest.raises(InvalidProductionOrderStateError, match="release evidence"):
        replace(order, status=ProductionOrderStatus.RELEASED)
    with pytest.raises(RoutingConsistencyError, match="released operations"):
        replace(released, operations=in_progress.operations)
    with pytest.raises(LotTraceabilityError, match="released orders"):
        replace(released, output_lots=output)
    with pytest.raises(InvalidProductionOrderStateError, match="start evidence"):
        replace(released, status=ProductionOrderStatus.IN_PROGRESS)
    with pytest.raises(RoutingConsistencyError, match="execution evidence"):
        replace(
            released,
            status=ProductionOrderStatus.IN_PROGRESS,
            started_at=CREATED_AT + timedelta(hours=2),
            started_by=uuid4(),
        )
    with pytest.raises(LotTraceabilityError, match="finished output"):
        replace(in_progress, output_lots=output)
    with pytest.raises(InvalidProductionOrderStateError, match="completion evidence"):
        replace(in_progress, status=ProductionOrderStatus.COMPLETED)
    ready = ready_to_complete(order, bom, routing, _raw_material_id)
    completed = ready.complete(
        output_lots=(ProductionLotTrace(uuid4(), order.product_id, quantity("1")),),
        actor_id=uuid4(),
        occurred_at=CREATED_AT + timedelta(hours=6),
    )
    with pytest.raises(RoutingConsistencyError, match="completed routing"):
        replace(completed, operations=order.operations)


def test_aggregate_rejects_duplicate_materials_bad_routing_and_cross_tenant_operation() -> None:
    order, _, _, _ = draft_order()
    duplicate_material = (order.materials[0], order.materials[0])
    with pytest.raises(InvalidProductionValueError, match="unique"):
        replace(order, materials=duplicate_material)
    output_as_material = ProductionMaterialPlan(order.product_id, quantity("1"))
    with pytest.raises(InvalidProductionValueError, match="output"):
        replace(order, materials=(output_as_material,))
    with pytest.raises(RoutingConsistencyError, match="unique and ordered"):
        replace(order, operations=(order.operations[1], order.operations[0]))
    foreign_constraint = replace(
        order.operations[0].work_center,
        company_id=uuid4(),
    )
    with pytest.raises(ProductionScopeError, match="another company"):
        replace(
            order,
            operations=(replace(order.operations[0], work_center=foreign_constraint),),
        )
    with pytest.raises(ProductionScopeError, match="engineering snapshot"):
        replace(order, engineering=replace(order.engineering, product_id=uuid4()))
    with pytest.raises(UnitOfMeasureMismatchError, match="engineering output units"):
        replace(
            order,
            planned_quantity=quantity("5", UnitOfMeasure.KILOGRAM),
        )
    with pytest.raises(InvalidProductionValueError, match="output_lots"):
        replace(order, output_lots=cast(Any, []))


def test_operation_sequence_type_and_consumption_type_are_validated() -> None:
    order, bom, routing, _ = draft_order()
    released = release(order, bom, routing)
    with pytest.raises(InvalidProductionValueError, match="sequence"):
        released.start_operation(
            cast(Any, "10"),
            work_center=center(order, "CUT-01", "LASER"),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=2),
        )
    in_progress = start_first(order, bom, routing)
    with pytest.raises(InvalidProductionValueError, match="trace"):
        in_progress.record_consumption(cast(Any, "bad"))
    with pytest.raises(InvalidProductionOrderStateError):
        in_progress.cancel(
            reason="No longer allowed",
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=3),
        )


def test_invalid_state_transitions_are_rejected() -> None:
    order, bom, routing, _ = draft_order()
    with pytest.raises(InvalidProductionOrderStateError):
        order.start_operation(
            10,
            work_center=center(order, "CUT-01", "LASER"),
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=1),
        )
    with pytest.raises(InvalidProductionOrderStateError):
        order.complete_operation(
            10,
            actor_id=uuid4(),
            occurred_at=CREATED_AT + timedelta(hours=1),
        )
    released = release(order, bom, routing)
    with pytest.raises(InvalidProductionOrderStateError):
        release(released, bom, routing)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda order: replace(order, id=UUID(int=0)),
        lambda order: replace(order, order_number="bad number!"),
        lambda order: replace(order, due_on=date(2026, 1, 1)),
        lambda order: replace(order, planned_quantity=cast(Any, Decimal("1"))),
        lambda order: replace(order, engineering=cast(Any, "engineering")),
        lambda order: replace(order, materials=()),
        lambda order: replace(order, materials=cast(Any, ("bad",))),
        lambda order: replace(order, operations=()),
        lambda order: replace(order, operations=cast(Any, ("bad",))),
        lambda order: replace(order, status=cast(Any, "DRAFT")),
        lambda order: replace(order, record_version=0),
    ],
)
def test_order_constructor_rejects_invalid_aggregate_state(mutation: Any) -> None:
    order, _, _, _ = draft_order()
    with pytest.raises((InvalidProductionValueError, ProductionScopeError)):
        mutation(order)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProductionLotTrace(UUID(int=0), uuid4(), quantity("1")),
        lambda: ProductionLotTrace(uuid4(), uuid4(), cast(Any, Decimal("1"))),
        lambda: ProductionMaterialPlan(uuid4(), cast(Any, Decimal("1"))),
        lambda: ProductionMaterialPlan(uuid4(), quantity("1"), cast(Any, ["bad"])),
        lambda: ProductionOrderOperation.from_routing(cast(Any, "operation")),
        lambda: ProductionOrderOperation(0, "Cut", cast(Any, "constraint")),
        lambda: ProductionOrderOperation(
            1,
            "Cut",
            WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-1"),)),
            cast(Any, "PENDING"),
        ),
    ],
)
def test_order_value_objects_reject_invalid_values(factory: Any) -> None:
    with pytest.raises(InvalidProductionValueError):
        factory()


def test_engineering_snapshot_rejects_invalid_capture_and_internal_state() -> None:
    order, bom, routing, _ = draft_order()
    capture: Any = ProductionEngineeringSnapshot.capture

    with pytest.raises(InvalidProductionValueError, match="bom must"):
        capture(
            bom="bad",
            routing=routing,
            approved_at=CREATED_AT,
            approved_by=uuid4(),
            planned_start_on=PLANNED_START,
        )
    with pytest.raises(InvalidProductionValueError, match="routing must"):
        capture(
            bom=bom,
            routing="bad",
            approved_at=CREATED_AT,
            approved_by=uuid4(),
            planned_start_on=PLANNED_START,
        )
    with pytest.raises(InvalidProductionValueError, match="timezone-aware"):
        capture(
            bom=bom,
            routing=routing,
            approved_at=CREATED_AT.replace(tzinfo=None),
            approved_by=uuid4(),
            planned_start_on=PLANNED_START,
        )
    with pytest.raises(InvalidProductionValueError, match="must be a date"):
        capture(
            bom=bom,
            routing=routing,
            approved_at=CREATED_AT,
            approved_by=uuid4(),
            planned_start_on=cast(Any, CREATED_AT),
        )
    with pytest.raises(InvalidProductionValueError, match="engineering versions"):
        replace(order.engineering, bom_version=cast(Any, "R1"))
    with pytest.raises(InvalidProductionValueError, match="record versions"):
        replace(order.engineering, bom_record_version=0)
    with pytest.raises(InvalidProductionValueError, match="bom_output_quantity"):
        replace(order.engineering, bom_output_quantity=cast(Any, Decimal("1")))


def test_operation_constructor_rejects_name_and_constraint_types() -> None:
    constraint = WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-01"),))
    with pytest.raises(InvalidProductionValueError, match="operation name"):
        ProductionOrderOperation(1, "", constraint)
    with pytest.raises(InvalidProductionValueError, match="work_center must"):
        ProductionOrderOperation(1, "Cut", cast(Any, "WC-01"))


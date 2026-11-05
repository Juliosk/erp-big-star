"""Deterministic gross-to-net and planned-order tests for MRP."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    BomNotFoundError,
    EngineeringUnavailableError,
    EngineeringVersion,
    InvalidProductionValueError,
    MRPAlertKind,
    MRPDemand,
    MRPDemandSource,
    MRPEngine,
    MRPInventoryPosition,
    MRPNetRequirement,
    MRPPlan,
    MRPPlannedOrder,
    MRPPlannedOrderType,
    MRPPlanningAlert,
    MRPPlanningPolicy,
    MRPPolicyNotFoundError,
    MRPScheduledReceipt,
    MRPScheduledReceiptType,
    MRPSupplyMode,
    ProductionQuantity,
    ProductionScopeError,
    UnitOfMeasure,
    UnitOfMeasureMismatchError,
)

AS_OF = date(2026, 11, 5)


def quantity(
    value: str,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
) -> ProductionQuantity:
    return ProductionQuantity(Decimal(value), unit)


def version(*, effective_until: date | None = None) -> EngineeringVersion:
    return EngineeringVersion("R1", 1, date(2026, 11, 1), effective_until)


def bom(
    company_id: UUID,
    product_id: UUID,
    output: ProductionQuantity,
    *items: BomItem,
    effective_until: date | None = None,
) -> BillOfMaterials:
    return BillOfMaterials(
        company_id=company_id,
        product_id=product_id,
        version=version(effective_until=effective_until),
        output_quantity=output,
        items=items,
    )


def policy(
    company_id: UUID,
    product_id: UUID,
    mode: MRPSupplyMode,
    minimum: str,
    lead_time_days: int,
    *,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
    multiple: str | None = None,
) -> MRPPlanningPolicy:
    return MRPPlanningPolicy(
        company_id=company_id,
        product_id=product_id,
        supply_mode=mode,
        minimum_lot=quantity(minimum, unit),
        lead_time_days=lead_time_days,
        lot_multiple=quantity(multiple, unit) if multiple is not None else None,
    )


def demand(
    company_id: UUID,
    product_id: UUID,
    value: str,
    required_on: date,
    *,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
    source_id: UUID | None = None,
) -> MRPDemand:
    return MRPDemand(
        company_id=company_id,
        source_id=source_id or uuid4(),
        source=MRPDemandSource.SALES_ORDER,
        product_id=product_id,
        quantity=quantity(value, unit),
        required_on=required_on,
    )


def test_multilevel_gross_to_net_generates_make_and_buy_orders() -> None:
    company_id = uuid4()
    finished_id = uuid4()
    subassembly_id = uuid4()
    raw_id = uuid4()
    finished_bom = bom(
        company_id,
        finished_id,
        quantity("1"),
        BomItem(subassembly_id, quantity("2")),
        BomItem(raw_id, quantity("1", UnitOfMeasure.KILOGRAM)),
    )
    subassembly_bom = bom(
        company_id,
        subassembly_id,
        quantity("1"),
        BomItem(raw_id, quantity("3", UnitOfMeasure.KILOGRAM)),
    )
    engine = MRPEngine(
        company_id,
        (finished_bom, subassembly_bom),
        (
            policy(company_id, finished_id, MRPSupplyMode.MAKE, "5", 2, multiple="5"),
            policy(company_id, subassembly_id, MRPSupplyMode.MAKE, "10", 3, multiple="10"),
            policy(
                company_id,
                raw_id,
                MRPSupplyMode.BUY,
                "25",
                5,
                unit=UnitOfMeasure.KILOGRAM,
                multiple="25",
            ),
        ),
    )
    sales = demand(company_id, finished_id, "10", date(2026, 11, 20))
    plan = engine.plan(
        as_of=AS_OF,
        demands=(sales,),
        inventory=(
            MRPInventoryPosition(company_id, finished_id, UnitOfMeasure.EACH, Decimal("2")),
            MRPInventoryPosition(company_id, subassembly_id, UnitOfMeasure.EACH, Decimal("5")),
            MRPInventoryPosition(
                company_id,
                raw_id,
                UnitOfMeasure.KILOGRAM,
                Decimal("10"),
            ),
        ),
        scheduled_receipts=(
            MRPScheduledReceipt(
                company_id,
                uuid4(),
                MRPScheduledReceiptType.PRODUCTION_ORDER,
                finished_id,
                quantity("1"),
                date(2026, 11, 19),
            ),
            MRPScheduledReceipt(
                company_id,
                uuid4(),
                MRPScheduledReceiptType.PURCHASE_ORDER,
                raw_id,
                quantity("20", UnitOfMeasure.KILOGRAM),
                date(2026, 11, 14),
            ),
        ),
    )

    assert [order.order_type for order in plan.planned_orders] == [
        MRPPlannedOrderType.MANUFACTURE,
        MRPPlannedOrderType.MANUFACTURE,
        MRPPlannedOrderType.PURCHASE,
    ]
    finished, subassembly, raw = plan.planned_orders
    assert finished.quantity == quantity("10")
    assert (finished.due_on, finished.release_on) == (
        date(2026, 11, 20),
        date(2026, 11, 18),
    )
    assert subassembly.quantity == quantity("20")
    assert (subassembly.due_on, subassembly.release_on) == (
        date(2026, 11, 18),
        date(2026, 11, 15),
    )
    assert raw.quantity == quantity("50", UnitOfMeasure.KILOGRAM)
    assert (raw.due_on, raw.release_on) == (
        date(2026, 11, 15),
        date(2026, 11, 10),
    )
    raw_lines = [line for line in plan.requirements if line.product_id == raw_id]
    assert [(line.required_on, line.gross_amount) for line in raw_lines] == [
        (date(2026, 11, 15), Decimal("60.000000")),
        (date(2026, 11, 18), Decimal("10.000000")),
    ]
    assert raw_lines[0].net_amount == Decimal("30.000000")
    assert raw_lines[0].scheduled_receipts_applied == Decimal("20.000000")
    assert raw_lines[0].projected_available == Decimal("20.000000")
    assert raw_lines[1].net_amount == Decimal("0.000000")
    assert plan.alerts == ()
    assert engine.plan(
        as_of=AS_OF,
        demands=(sales,),
        inventory=(
            MRPInventoryPosition(company_id, finished_id, UnitOfMeasure.EACH, Decimal("2")),
            MRPInventoryPosition(company_id, subassembly_id, UnitOfMeasure.EACH, Decimal("5")),
            MRPInventoryPosition(
                company_id,
                raw_id,
                UnitOfMeasure.KILOGRAM,
                Decimal("10"),
            ),
        ),
        scheduled_receipts=plan_input_receipts(company_id, finished_id, raw_id),
    ) == plan


def plan_input_receipts(
    company_id: UUID,
    finished_id: UUID,
    raw_id: UUID,
) -> tuple[MRPScheduledReceipt, ...]:
    """Build equivalent receipts to prove planning is deterministic by business data."""
    return (
        MRPScheduledReceipt(
            company_id,
            uuid4(),
            MRPScheduledReceiptType.PRODUCTION_ORDER,
            finished_id,
            quantity("1"),
            date(2026, 11, 19),
        ),
        MRPScheduledReceipt(
            company_id,
            uuid4(),
            MRPScheduledReceiptType.PURCHASE_ORDER,
            raw_id,
            quantity("20", UnitOfMeasure.KILOGRAM),
            date(2026, 11, 14),
        ),
    )


def test_inventory_and_scheduled_supply_fully_offset_demand() -> None:
    company_id = uuid4()
    product_id = uuid4()
    source_id = uuid4()
    receipt_id = uuid4()
    engine = MRPEngine(
        company_id,
        (),
        (policy(company_id, product_id, MRPSupplyMode.BUY, "5", 2),),
    )
    inputs = (
        demand(
            company_id,
            product_id,
            "5",
            date(2026, 11, 10),
            source_id=source_id,
        ),
    )
    stock = (
        MRPInventoryPosition(
            company_id,
            product_id,
            UnitOfMeasure.EACH,
            on_hand=Decimal("5"),
            allocated=Decimal("1"),
            safety_stock=Decimal("1"),
        ),
    )
    receipts = (
        MRPScheduledReceipt(
            company_id,
            receipt_id,
            MRPScheduledReceiptType.PURCHASE_ORDER,
            product_id,
            quantity("4"),
            date(2026, 11, 9),
        ),
    )

    first = engine.plan(
        as_of=AS_OF,
        demands=inputs,
        inventory=stock,
        scheduled_receipts=receipts,
    )
    second = engine.plan(
        as_of=AS_OF,
        demands=inputs,
        inventory=stock,
        scheduled_receipts=receipts,
    )
    assert first == second
    assert first.planned_orders == ()
    assert first.requirements[0].available_applied == Decimal("3.000000")
    assert first.requirements[0].scheduled_receipts_applied == Decimal("2.000000")
    assert first.requirements[0].net_amount == Decimal("0.000000")
    assert first.requirements[0].projected_available == Decimal("2.000000")


def test_covered_parent_does_not_explode_components_and_same_period_demands_merge() -> None:
    company_id = uuid4()
    product_id = uuid4()
    component_id = uuid4()
    structure = bom(
        company_id,
        product_id,
        quantity("1"),
        BomItem(component_id, quantity("2")),
    )
    engine = MRPEngine(
        company_id,
        (structure,),
        (policy(company_id, product_id, MRPSupplyMode.MAKE, "1", 1),),
    )
    first_source = uuid4()
    second_source = uuid4()
    plan = engine.plan(
        as_of=AS_OF,
        demands=(
            demand(
                company_id,
                product_id,
                "2",
                date(2026, 11, 10),
                source_id=first_source,
            ),
            demand(
                company_id,
                product_id,
                "3",
                date(2026, 11, 10),
                source_id=second_source,
            ),
        ),
        inventory=(
            MRPInventoryPosition(
                company_id,
                product_id,
                UnitOfMeasure.EACH,
                Decimal("5"),
            ),
        ),
    )
    assert len(plan.requirements) == 1
    assert plan.requirements[0].gross_amount == Decimal("5.000000")
    assert set(plan.requirements[0].source_ids) == {first_source, second_source}
    assert plan.planned_orders == ()


def test_allocations_minimum_lot_and_lead_time_bottleneck_are_explainable() -> None:
    company_id = uuid4()
    product_id = uuid4()
    engine = MRPEngine(
        company_id,
        (),
        (
            policy(
                company_id,
                product_id,
                MRPSupplyMode.BUY,
                "4",
                5,
                multiple="3",
            ),
        ),
    )
    plan = engine.plan(
        as_of=AS_OF,
        demands=(demand(company_id, product_id, "1", date(2026, 11, 7)),),
        inventory=(
            MRPInventoryPosition(
                company_id,
                product_id,
                UnitOfMeasure.EACH,
                on_hand=Decimal("2"),
                allocated=Decimal("5"),
                safety_stock=Decimal("1"),
            ),
        ),
        scheduled_receipts=(
            MRPScheduledReceipt(
                company_id,
                uuid4(),
                MRPScheduledReceiptType.PURCHASE_ORDER,
                product_id,
                quantity("20"),
                date(2026, 11, 8),
            ),
        ),
    )
    line = plan.requirements[0]
    order = plan.planned_orders[0]
    alert = plan.alerts[0]
    assert line.net_amount == Decimal("5.000000")
    assert order.quantity == quantity("6")
    assert order.release_on == date(2026, 11, 2)
    assert alert.kind is MRPAlertKind.LEAD_TIME_CONSTRAINT
    assert alert.days_past_due == 3
    assert alert.planned_order_id == order.id


def test_missing_policy_bom_and_effective_engineering_fail_closed() -> None:
    company_id = uuid4()
    product_id = uuid4()
    component_id = uuid4()
    required = (demand(company_id, product_id, "1", date(2026, 11, 10)),)
    with pytest.raises(MRPPolicyNotFoundError):
        MRPEngine(company_id, (), ()).plan(as_of=AS_OF, demands=required)

    make_policy = policy(company_id, product_id, MRPSupplyMode.MAKE, "1", 1)
    with pytest.raises(BomNotFoundError):
        MRPEngine(company_id, (), (make_policy,)).plan(
            as_of=AS_OF,
            demands=required,
        )

    expired = bom(
        company_id,
        product_id,
        quantity("1"),
        BomItem(component_id, quantity("1")),
        effective_until=date(2026, 11, 9),
    )
    with pytest.raises(EngineeringUnavailableError):
        MRPEngine(company_id, (expired,), (make_policy,)).plan(
            as_of=AS_OF,
            demands=required,
        )


def test_engine_and_plan_inputs_are_tenant_bound_and_unique() -> None:
    company_id = uuid4()
    foreign_id = uuid4()
    product_id = uuid4()
    component_id = uuid4()
    own_policy = policy(company_id, product_id, MRPSupplyMode.BUY, "1", 1)
    foreign_policy = replace(own_policy, company_id=foreign_id)
    with pytest.raises(ProductionScopeError):
        MRPEngine(company_id, (), (foreign_policy,))
    own_bom = bom(
        company_id,
        product_id,
        quantity("1"),
        BomItem(component_id, quantity("1")),
    )
    with pytest.raises(ProductionScopeError):
        MRPEngine(company_id, (replace(own_bom, company_id=foreign_id),), ())
    with pytest.raises(InvalidProductionValueError, match="one active BOM"):
        MRPEngine(company_id, (own_bom, own_bom), ())
    with pytest.raises(InvalidProductionValueError, match="one planning policy"):
        MRPEngine(company_id, (), (own_policy, own_policy))

    engine = MRPEngine(company_id, (), (own_policy,))
    source_id = uuid4()
    requested = demand(
        company_id,
        product_id,
        "1",
        date(2026, 11, 10),
        source_id=source_id,
    )
    with pytest.raises(ProductionScopeError):
        engine.plan(
            as_of=AS_OF,
            demands=(replace(requested, company_id=foreign_id),),
        )
    with pytest.raises(InvalidProductionValueError, match="source identifiers"):
        engine.plan(as_of=AS_OF, demands=(requested, requested))
    position = MRPInventoryPosition(company_id, product_id, UnitOfMeasure.EACH)
    with pytest.raises(InvalidProductionValueError, match="inventory positions"):
        engine.plan(
            as_of=AS_OF,
            demands=(requested,),
            inventory=(position, position),
        )
    receipt = MRPScheduledReceipt(
        company_id,
        uuid4(),
        MRPScheduledReceiptType.PURCHASE_ORDER,
        product_id,
        quantity("1"),
        date(2026, 11, 9),
    )
    with pytest.raises(InvalidProductionValueError, match="receipt identifiers"):
        engine.plan(
            as_of=AS_OF,
            demands=(requested,),
            scheduled_receipts=(receipt, receipt),
        )


def test_units_and_input_shapes_are_strict() -> None:
    company_id = uuid4()
    product_id = uuid4()
    engine = MRPEngine(
        company_id,
        (),
        (policy(company_id, product_id, MRPSupplyMode.BUY, "1", 1),),
    )
    requested = demand(company_id, product_id, "1", date(2026, 11, 10))
    with pytest.raises(InvalidProductionValueError, match="as_of"):
        engine.plan(as_of=cast(Any, "2026-11-05"), demands=(requested,))
    with pytest.raises(InvalidProductionValueError, match="non-empty"):
        engine.plan(as_of=AS_OF, demands=())
    with pytest.raises(InvalidProductionValueError, match="MRPDemand"):
        engine.plan(as_of=AS_OF, demands=cast(Any, ("bad",)))
    with pytest.raises(UnitOfMeasureMismatchError, match="inventory"):
        engine.plan(
            as_of=AS_OF,
            demands=(requested,),
            inventory=(
                MRPInventoryPosition(
                    company_id,
                    product_id,
                    UnitOfMeasure.KILOGRAM,
                ),
            ),
        )
    with pytest.raises(UnitOfMeasureMismatchError, match="scheduled receipt"):
        engine.plan(
            as_of=AS_OF,
            demands=(requested,),
            scheduled_receipts=(
                MRPScheduledReceipt(
                    company_id,
                    uuid4(),
                    MRPScheduledReceiptType.PURCHASE_ORDER,
                    product_id,
                    quantity("1", UnitOfMeasure.KILOGRAM),
                    date(2026, 11, 9),
                ),
            ),
        )
    other = demand(
        company_id,
        product_id,
        "1",
        date(2026, 11, 10),
        unit=UnitOfMeasure.KILOGRAM,
    )
    with pytest.raises(UnitOfMeasureMismatchError, match="different units"):
        engine.plan(as_of=AS_OF, demands=(requested, other))


def test_planning_policy_sizing_contract() -> None:
    company_id = uuid4()
    product_id = uuid4()
    configured = policy(
        company_id,
        product_id,
        MRPSupplyMode.BUY,
        "4",
        1,
        multiple="3",
    )
    assert configured.size(Decimal("5"), UnitOfMeasure.EACH) == quantity("6")
    with pytest.raises(InvalidProductionValueError, match="positive"):
        configured.size(Decimal("0"), UnitOfMeasure.EACH)
    with pytest.raises(UnitOfMeasureMismatchError):
        configured.size(Decimal("1"), UnitOfMeasure.KILOGRAM)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: MRPDemand(
            uuid4(), uuid4(), cast(Any, "SALES"), uuid4(), quantity("1"), AS_OF
        ),
        lambda: MRPInventoryPosition(
            uuid4(), uuid4(), cast(Any, "EA"), Decimal("0")
        ),
        lambda: MRPInventoryPosition(
            uuid4(), uuid4(), UnitOfMeasure.EACH, Decimal("-1")
        ),
        lambda: MRPScheduledReceipt(
            uuid4(),
            uuid4(),
            cast(Any, "PO"),
            uuid4(),
            quantity("1"),
            AS_OF,
        ),
        lambda: MRPPlanningPolicy(
            uuid4(),
            uuid4(),
            cast(Any, "BUY"),
            quantity("1"),
            1,
        ),
        lambda: MRPPlanningPolicy(
            uuid4(),
            uuid4(),
            MRPSupplyMode.BUY,
            quantity("1"),
            -1,
        ),
        lambda: MRPPlanningPolicy(
            uuid4(),
            uuid4(),
            MRPSupplyMode.BUY,
            quantity("1"),
            1,
            quantity("1", UnitOfMeasure.KILOGRAM),
        ),
        lambda: MRPEngine(uuid4(), cast(Any, ("bad",)), ()),
        lambda: MRPEngine(uuid4(), (), cast(Any, ("bad",))),
    ],
)
def test_invalid_mrp_values_fail_fast(factory: Any) -> None:
    with pytest.raises((InvalidProductionValueError, UnitOfMeasureMismatchError)):
        factory()


def test_result_value_objects_reject_invalid_state() -> None:
    company_id = uuid4()
    product_id = uuid4()
    source_id = uuid4()
    line = MRPNetRequirement(
        company_id,
        product_id,
        AS_OF,
        UnitOfMeasure.EACH,
        Decimal("1"),
        Decimal("0"),
        Decimal("0"),
        Decimal("1"),
        Decimal("1"),
        Decimal("0"),
        (source_id,),
    )
    planned = MRPPlannedOrder(
        uuid4(),
        company_id,
        MRPPlannedOrderType.PURCHASE,
        product_id,
        quantity("1"),
        AS_OF,
        AS_OF,
        (source_id,),
    )
    alert = MRPPlanningAlert(
        company_id,
        MRPAlertKind.LEAD_TIME_CONSTRAINT,
        planned.id,
        product_id,
        AS_OF,
        date(2026, 11, 4),
        1,
    )
    requested = demand(company_id, product_id, "1", AS_OF, source_id=source_id)
    plan = MRPPlan(company_id, AS_OF, (requested,), (line,), (planned,), (alert,))
    assert plan.planned_orders == (planned,)
    with pytest.raises(ProductionScopeError):
        replace(plan, requirements=(replace(line, company_id=uuid4()),))
    with pytest.raises(InvalidProductionValueError, match="requirements"):
        replace(plan, requirements=cast(Any, [line]))
    with pytest.raises(InvalidProductionValueError, match="source_ids"):
        replace(line, source_ids=())
    with pytest.raises(InvalidProductionValueError, match="unique"):
        replace(line, source_ids=(source_id, source_id))
    with pytest.raises(InvalidProductionValueError, match="release_on"):
        replace(planned, release_on=date(2026, 11, 6))
    with pytest.raises(InvalidProductionValueError, match="days_past_due"):
        replace(alert, days_past_due=0)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: MRPDemand(
                uuid4(),
                uuid4(),
                MRPDemandSource.FORECAST,
                uuid4(),
                cast(Any, Decimal("1")),
                AS_OF,
            ),
            "quantity",
        ),
        (
            lambda: replace(
                demand(uuid4(), uuid4(), "1", AS_OF),
                required_on=cast(Any, "2026-11-05"),
            ),
            "required_on",
        ),
        (
            lambda: MRPScheduledReceipt(
                uuid4(),
                uuid4(),
                MRPScheduledReceiptType.PURCHASE_ORDER,
                uuid4(),
                cast(Any, Decimal("1")),
                AS_OF,
            ),
            "quantity",
        ),
        (
            lambda: MRPPlanningPolicy(
                uuid4(),
                uuid4(),
                MRPSupplyMode.BUY,
                cast(Any, Decimal("1")),
                1,
            ),
            "minimum_lot",
        ),
        (
            lambda: MRPPlanningPolicy(
                uuid4(),
                uuid4(),
                MRPSupplyMode.BUY,
                quantity("1"),
                1,
                cast(Any, Decimal("1")),
            ),
            "lot_multiple",
        ),
        (
            lambda: MRPNetRequirement(
                uuid4(),
                uuid4(),
                AS_OF,
                cast(Any, "EA"),
                Decimal("1"),
                Decimal("0"),
                Decimal("0"),
                Decimal("1"),
                Decimal("1"),
                Decimal("0"),
                (uuid4(),),
            ),
            "unit",
        ),
        (
            lambda: replace(
                MRPNetRequirement(
                    uuid4(),
                    uuid4(),
                    AS_OF,
                    UnitOfMeasure.EACH,
                    Decimal("1"),
                    Decimal("0"),
                    Decimal("0"),
                    Decimal("1"),
                    Decimal("1"),
                    Decimal("0"),
                    (uuid4(),),
                ),
                source_ids=(UUID(int=0),),
            ),
            "non-zero UUID",
        ),
        (
            lambda: MRPPlannedOrder(
                uuid4(),
                uuid4(),
                cast(Any, "PURCHASE"),
                uuid4(),
                quantity("1"),
                AS_OF,
                AS_OF,
                (uuid4(),),
            ),
            "order_type",
        ),
        (
            lambda: MRPPlannedOrder(
                uuid4(),
                uuid4(),
                MRPPlannedOrderType.PURCHASE,
                uuid4(),
                cast(Any, Decimal("1")),
                AS_OF,
                AS_OF,
                (uuid4(),),
            ),
            "quantity",
        ),
        (
            lambda: MRPPlannedOrder(
                uuid4(),
                uuid4(),
                MRPPlannedOrderType.PURCHASE,
                uuid4(),
                quantity("1"),
                AS_OF,
                AS_OF,
                (),
            ),
            "source_ids",
        ),
        (
            lambda: MRPPlannedOrder(
                uuid4(),
                uuid4(),
                MRPPlannedOrderType.PURCHASE,
                uuid4(),
                quantity("1"),
                AS_OF,
                AS_OF,
                (UUID(int=0),),
            ),
            "non-zero UUID",
        ),
        (
            lambda: MRPPlanningAlert(
                uuid4(),
                cast(Any, "LEAD_TIME"),
                uuid4(),
                uuid4(),
                AS_OF,
                date(2026, 11, 4),
                1,
            ),
            "kind",
        ),
    ],
)
def test_value_object_defensive_contracts(factory: Any, message: str) -> None:
    with pytest.raises(InvalidProductionValueError, match=message):
        factory()

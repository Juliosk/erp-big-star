"""Pure tests for BOM expansion, engineering values and routing constraints."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.production.domain import (
    BillOfMaterials,
    BomCycleError,
    BomExpansionService,
    BomItem,
    BomNotFoundError,
    EngineeringVersion,
    InvalidProductionValueError,
    ProductionQuantity,
    ProductionRouting,
    ProductionScopeError,
    ProductionVersionConflictError,
    RoutingOperation,
    ScrapRate,
    UnitOfMeasure,
    UnitOfMeasureMismatchError,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)


def version(code: str = "R1") -> EngineeringVersion:
    return EngineeringVersion(code=code, revision=1, effective_from=date(2026, 11, 4))


def quantity(value: str, unit: UnitOfMeasure = UnitOfMeasure.EACH) -> ProductionQuantity:
    return ProductionQuantity(Decimal(value), unit)


def bom(
    company_id: UUID,
    product_id: UUID,
    *items: BomItem,
    output: ProductionQuantity | None = None,
) -> BillOfMaterials:
    return BillOfMaterials(
        company_id=company_id,
        product_id=product_id,
        version=version(),
        output_quantity=output or quantity("1"),
        items=items,
    )


def item(
    product_id: UUID,
    amount: str,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
    scrap: str = "0",
) -> BomItem:
    return BomItem(product_id, quantity(amount, unit), ScrapRate(Decimal(scrap)))


def test_multilevel_expansion_aggregates_leaf_inputs_and_scrap() -> None:
    company_id = uuid4()
    finished, assembly, steel, paint = uuid4(), uuid4(), uuid4(), uuid4()
    service = BomExpansionService(
        company_id,
        (
            bom(
                company_id,
                finished,
                item(assembly, "2"),
                item(steel, "1", UnitOfMeasure.KILOGRAM),
            ),
            bom(
                company_id,
                assembly,
                item(steel, "3", UnitOfMeasure.KILOGRAM, "0.10"),
                item(paint, "0.25", UnitOfMeasure.LITER),
            ),
        ),
    )

    requirements = {
        requirement.product_id: requirement.quantity
        for requirement in service.expand(finished, quantity("1"))
    }

    assert requirements[steel] == quantity("7.666667", UnitOfMeasure.KILOGRAM)
    assert requirements[paint] == quantity("0.500000", UnitOfMeasure.LITER)
    assert assembly not in requirements


def test_expansion_scales_against_bom_output_quantity() -> None:
    company_id, finished, fabric = uuid4(), uuid4(), uuid4()
    service = BomExpansionService(
        company_id,
        (
            bom(
                company_id,
                finished,
                item(fabric, "5", UnitOfMeasure.METER),
                output=quantity("2"),
            ),
        ),
    )

    result = service.expand(finished, quantity("6"))

    assert result[0].product_id == fabric
    assert result[0].quantity == quantity("15", UnitOfMeasure.METER)


def test_indirect_circular_bom_is_rejected_before_expansion() -> None:
    company_id, product_a, product_b, product_c = uuid4(), uuid4(), uuid4(), uuid4()

    with pytest.raises(BomCycleError, match="circular BOM structure") as captured:
        BomExpansionService(
            company_id,
            (
                bom(company_id, product_a, item(product_b, "1")),
                bom(company_id, product_b, item(product_c, "1")),
                bom(company_id, product_c, item(product_a, "1")),
            ),
        )

    assert captured.value.code == "BOM_CYCLE_DETECTED"


def test_direct_self_consumption_is_rejected() -> None:
    company_id, product_id = uuid4(), uuid4()

    with pytest.raises(BomCycleError, match="own product"):
        bom(company_id, product_id, item(product_id, "1"))


def test_expansion_rejects_missing_root_and_incompatible_units() -> None:
    company_id, root, leaf = uuid4(), uuid4(), uuid4()
    service = BomExpansionService(company_id, (bom(company_id, root, item(leaf, "1")),))

    with pytest.raises(BomNotFoundError):
        service.expand(uuid4(), quantity("1"))
    with pytest.raises(UnitOfMeasureMismatchError, match="output unit"):
        service.expand(root, quantity("1", UnitOfMeasure.KILOGRAM))


def test_same_leaf_cannot_be_aggregated_in_different_units() -> None:
    company_id, root, left, right, leaf = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    service = BomExpansionService(
        company_id,
        (
            bom(company_id, root, item(left, "1"), item(right, "1")),
            bom(company_id, left, item(leaf, "1", UnitOfMeasure.KILOGRAM)),
            bom(company_id, right, item(leaf, "1", UnitOfMeasure.LITER)),
        ),
    )

    with pytest.raises(UnitOfMeasureMismatchError, match="different units"):
        service.expand(root, quantity("1"))


def test_bom_catalogue_is_tenant_bound_and_has_one_active_version() -> None:
    company_id, other_company_id, root, leaf = uuid4(), uuid4(), uuid4(), uuid4()
    first = bom(company_id, root, item(leaf, "1"))

    with pytest.raises(ProductionScopeError, match="expansion company"):
        BomExpansionService(company_id, (bom(other_company_id, root, item(leaf, "1")),))
    with pytest.raises(InvalidProductionValueError, match="one BOM version"):
        BomExpansionService(company_id, (first, first))


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: ProductionQuantity(Decimal("0"), UnitOfMeasure.EACH), "positive"),
        (lambda: ProductionQuantity(Decimal("NaN"), UnitOfMeasure.EACH), "finite Decimal"),
        (
            lambda: ProductionQuantity(
                Decimal("1"), cast(UnitOfMeasure, "EA")
            ),
            "UnitOfMeasure",
        ),
        (lambda: ScrapRate(Decimal("1")), "between 0"),
        (lambda: ScrapRate(Decimal("-0.1")), "between 0"),
        (
            lambda: EngineeringVersion("bad code!", 1, date(2026, 1, 1)),
            "code is invalid",
        ),
        (
            lambda: EngineeringVersion("R1", 0, date(2026, 1, 1)),
            "positive integer",
        ),
        (
            lambda: EngineeringVersion(
                "R1", 1, date(2026, 2, 1), date(2026, 1, 1)
            ),
            "cannot precede",
        ),
    ],
)
def test_exact_production_values_reject_invalid_input(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(InvalidProductionValueError, match=message):
        factory()


def test_value_objects_normalize_and_remain_immutable() -> None:
    current_version = EngineeringVersion(" rev-1 ", 2, date(2026, 1, 1))
    bounded_version = EngineeringVersion(
        "REV-2", 3, date(2026, 2, 1), date(2026, 12, 31)
    )
    result = quantity("2").scaled_by(Decimal("1.5"))

    assert current_version.code == "REV-1"
    assert bounded_version.effective_until == date(2026, 12, 31)
    assert result.amount == Decimal("3.000000")
    with pytest.raises(FrozenInstanceError):
        result.amount = Decimal("4")  # type: ignore[misc]


def test_work_center_constraints_and_routing_are_tenant_bound() -> None:
    company_id = uuid4()
    cutting = WorkCenter(
        company_id,
        WorkCenterCode(" cut-01 "),
        frozenset({"laser", "precision"}),
    )
    constraint = WorkCenterConstraint(
        company_id,
        (WorkCenterCode("CUT-01"), WorkCenterCode("CUT-02")),
        frozenset({"LASER"}),
    )
    operation = RoutingOperation(
        sequence=10,
        name="  Precision cutting ",
        work_center=constraint,
        setup_minutes=Decimal("5"),
        run_minutes_per_unit=Decimal("0.5"),
    )
    routing = ProductionRouting(
        company_id=company_id,
        product_id=uuid4(),
        version=version(),
        operations=(operation,),
    )

    assert constraint.accepts(cutting)
    assert operation.name == "Precision cutting"
    assert routing.operations == (operation,)
    assert not constraint.accepts(
        WorkCenter(company_id, WorkCenterCode("CUT-02"), frozenset({"MANUAL"}))
    )
    with pytest.raises(ProductionScopeError):
        constraint.accepts(
            WorkCenter(uuid4(), WorkCenterCode("CUT-01"), frozenset({"LASER"}))
        )


def test_routing_rejects_duplicate_unordered_or_cross_tenant_operations() -> None:
    company_id = uuid4()
    constraint = WorkCenterConstraint(company_id, (WorkCenterCode("WC-1"),))
    first = RoutingOperation(20, "Finish", constraint, Decimal("0"), Decimal("1"))
    second = RoutingOperation(10, "Cut", constraint, Decimal("1"), Decimal("1"))

    with pytest.raises(InvalidProductionValueError, match="unique and ordered"):
        ProductionRouting(company_id, uuid4(), version(), (first, second))
    foreign = RoutingOperation(
        30,
        "Foreign",
        WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-X"),)),
        Decimal("1"),
        Decimal("1"),
    )
    with pytest.raises(ProductionScopeError, match="routing company"):
        ProductionRouting(company_id, uuid4(), version(), (foreign,))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: BomItem(uuid4(), cast(Any, "1")),
        lambda: BomItem(uuid4(), quantity("1"), cast(Any, Decimal("0"))),
        lambda: BillOfMaterials(
            uuid4(), uuid4(), cast(Any, "R1"), quantity("1"), (item(uuid4(), "1"),)
        ),
        lambda: BillOfMaterials(
            uuid4(), uuid4(), version(), cast(Any, Decimal("1")), (item(uuid4(), "1"),)
        ),
        lambda: BillOfMaterials(uuid4(), uuid4(), version(), quantity("1"), ()),
        lambda: BillOfMaterials(
            uuid4(), uuid4(), version(), quantity("1"), cast(Any, ("bad",))
        ),
        lambda: BillOfMaterials(
            uuid4(),
            uuid4(),
            version(),
            quantity("1"),
            (item(uuid4(), "1"),),
            record_version=0,
        ),
        lambda: (
            lambda company_id, product_id, component_id: BillOfMaterials(
                company_id,
                product_id,
                version(),
                quantity("1"),
                (item(component_id, "1"), item(component_id, "2")),
            )
        )(uuid4(), uuid4(), uuid4()),
        lambda: BomExpansionService(uuid4(), ()),
        lambda: BomExpansionService(uuid4(), cast(Any, ("bad",))),
    ],
)
def test_bom_contracts_reject_malformed_values(factory: Callable[[], object]) -> None:
    with pytest.raises(InvalidProductionValueError):
        factory()


def test_expansion_rejects_non_quantity_demand() -> None:
    company_id, root, leaf = uuid4(), uuid4(), uuid4()
    service = BomExpansionService(company_id, (bom(company_id, root, item(leaf, "1")),))

    with pytest.raises(InvalidProductionValueError, match="demanded_output"):
        service.expand(root, cast(Any, Decimal("1")))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: WorkCenter(uuid4(), cast(Any, "WC-1"), frozenset()),
        lambda: WorkCenter(uuid4(), WorkCenterCode("WC-1"), cast(Any, {"CUT"})),
        lambda: WorkCenter(
            uuid4(), WorkCenterCode("WC-1"), frozenset(), record_version=0
        ),
        lambda: WorkCenter(uuid4(), WorkCenterCode("WC-1"), cast(Any, frozenset({1}))),
        lambda: WorkCenterConstraint(uuid4(), ()),
        lambda: WorkCenterConstraint(uuid4(), cast(Any, ("WC-1",))),
        lambda: WorkCenterConstraint(
            uuid4(), (WorkCenterCode("WC-1"), WorkCenterCode("WC-1"))
        ),
        lambda: WorkCenterConstraint(
            uuid4(), (WorkCenterCode("WC-1"),), cast(Any, {"CUT"})
        ),
        lambda: WorkCenterConstraint(
            uuid4(), (WorkCenterCode("WC-1"),), cast(Any, frozenset({""}))
        ),
        lambda: RoutingOperation(
            0,
            "Cut",
            WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-1"),)),
            Decimal("0"),
            Decimal("1"),
        ),
        lambda: RoutingOperation(
            1,
            cast(Any, 123),
            WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-1"),)),
            Decimal("0"),
            Decimal("1"),
        ),
        lambda: RoutingOperation(
            1,
            " ",
            WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-1"),)),
            Decimal("0"),
            Decimal("1"),
        ),
        lambda: RoutingOperation(
            1, "Cut", cast(Any, "WC-1"), Decimal("0"), Decimal("1")
        ),
        lambda: RoutingOperation(
            1,
            "Cut",
            WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-1"),)),
            Decimal("-1"),
            Decimal("1"),
        ),
        lambda: ProductionRouting(uuid4(), uuid4(), cast(Any, "R1"), cast(Any, ())),
        lambda: ProductionRouting(uuid4(), uuid4(), version(), ()),
        lambda: ProductionRouting(uuid4(), uuid4(), version(), cast(Any, ("bad",))),
        lambda: (
            lambda company_id: ProductionRouting(
                company_id,
                uuid4(),
                version(),
                (
                    RoutingOperation(
                        1,
                        "Cut",
                        WorkCenterConstraint(company_id, (WorkCenterCode("WC-1"),)),
                        Decimal("0"),
                        Decimal("1"),
                    ),
                ),
                record_version=0,
            )
        )(uuid4()),
    ],
)
def test_routing_contracts_reject_malformed_values(factory: Callable[[], object]) -> None:
    with pytest.raises(InvalidProductionValueError):
        factory()


def test_constraint_rejects_non_work_center() -> None:
    constraint = WorkCenterConstraint(uuid4(), (WorkCenterCode("WC-1"),))

    with pytest.raises(InvalidProductionValueError, match="must be a WorkCenter"):
        constraint.accepts(cast(Any, "WC-1"))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProductionQuantity(Decimal("1"), UnitOfMeasure.EACH).scaled_by(
            Decimal("0")
        ),
        lambda: ScrapRate().gross_requirement(cast(Any, Decimal("1"))),
        lambda: EngineeringVersion(cast(Any, 1), 1, date(2026, 1, 1)),
        lambda: EngineeringVersion("R1", 1, cast(Any, "2026-01-01")),
        lambda: EngineeringVersion(
            "R1", 1, date(2026, 1, 1), cast(Any, "2026-02-01")
        ),
        lambda: WorkCenterCode(cast(Any, 1)),
        lambda: WorkCenterCode("bad code!"),
        lambda: ProductionQuantity(Decimal("1e100"), UnitOfMeasure.EACH),
    ],
)
def test_supporting_value_objects_reject_malformed_values(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(InvalidProductionValueError):
        factory()


def test_non_zero_uuid_is_required_at_domain_boundaries() -> None:
    with pytest.raises(InvalidProductionValueError, match="non-zero UUID"):
        BomItem(UUID(int=0), quantity("1"))


def test_version_conflict_exposes_stable_code_and_expected_version() -> None:
    error = ProductionVersionConflictError(3)

    error = ProductionVersionConflictError(3)

    assert error.code == "VERSION_CONFLICT"
    assert error.expected_version == 3
    assert "version 3" in str(error)


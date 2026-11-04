"""Pure deterministic Cash Flow alert-engine coverage."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    BusinessCalendar,
    CashAmount,
    CashFlowAlertDimension,
    CashFlowAlertEngine,
    CashFlowAlertPolicy,
    CashFlowAlertSeverity,
    CashFlowAlertSource,
    CashFlowAlertType,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowEngine,
    CashFlowExposure,
    CashFlowExposureKind,
    CashFlowItem,
    CashFlowOrigin,
    CashFlowProjection,
    CashFlowProjectionInput,
    CashFlowScenario,
    InvalidCashFlowError,
    ProjectionGranularity,
)

COMPANY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SCENARIO_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def _item(
    amount: str,
    occurs_on: date,
    *,
    reference_id: UUID | None = None,
    direction: CashFlowDirection = CashFlowDirection.OUTFLOW,
    category: CashFlowCategory = CashFlowCategory.OPERATING,
) -> CashFlowItem:
    return CashFlowItem(
        company_id=COMPANY_ID,
        amount=CashAmount(Decimal(amount)),
        occurs_on=occurs_on,
        direction=direction,
        category=category,
        certainty=CashFlowCertainty.COMMITTED,
        origin=(
            CashFlowOrigin.PAYABLE_INSTALLMENT
            if direction is CashFlowDirection.OUTFLOW
            else CashFlowOrigin.RECEIVABLE_INSTALLMENT
        ),
        reference_id=reference_id or uuid4(),
    )


def _projection(
    *,
    opening: str,
    reserve: str,
    items: tuple[CashFlowItem, ...],
    cost_rate: str = "0.0000",
) -> CashFlowProjection:
    horizon = CashFlowDateHorizon(date(2026, 11, 1), date(2026, 11, 7))
    return CashFlowEngine(BusinessCalendar()).project(
        CashFlowProjectionInput(
            projection_id=PROJECTION_ID,
            company_id=COMPANY_ID,
            as_of=horizon.start_on,
            calculated_at=NOW,
            horizon=horizon,
            granularity=ProjectionGranularity.DAILY,
            opening_balance=CashAmount(Decimal(opening)),
            minimum_reserve=CashAmount(Decimal(reserve)),
            scenario=CashFlowScenario(
                id=SCENARIO_ID,
                name="Stress",
                cost_variation_rate=Decimal(cost_rate),
            ),
            items=items,
        )
    )


def test_detects_first_operational_and_scenario_cash_rupture_deterministically() -> None:
    projection = _projection(
        opening="100.00",
        reserve="50.00",
        items=(_item("150.00", date(2026, 11, 1)),),
    )
    engine = CashFlowAlertEngine()

    first = engine.evaluate(projection, source=CashFlowAlertSource.PROJECTION)
    second = engine.evaluate(projection, source=CashFlowAlertSource.PROJECTION)

    rupture = [item for item in first if item.alert_type is CashFlowAlertType.CASH_RUPTURE]
    assert len(rupture) == 2
    assert {item.dimension for item in rupture} == {
        CashFlowAlertDimension.OPERATIONAL_BALANCE,
        CashFlowAlertDimension.SCENARIO_BALANCE,
    }
    assert all(item.severity is CashFlowAlertSeverity.CRITICAL for item in rupture)
    assert all(item.actual_value == Decimal("-50.00") for item in rupture)
    assert [item.id for item in first] == [item.id for item in second]


def test_safety_threshold_is_not_mislabeled_as_negative_rupture() -> None:
    projection = _projection(
        opening="100.00",
        reserve="50.00",
        items=(_item("60.00", date(2026, 11, 1)),),
    )
    alerts = CashFlowAlertEngine().evaluate(
        projection, source=CashFlowAlertSource.SCENARIO
    )
    safety = [item for item in alerts if item.alert_type is CashFlowAlertType.SAFETY_THRESHOLD]
    assert len(safety) == 1
    assert safety[0].dimension is CashFlowAlertDimension.SCENARIO_BALANCE
    assert safety[0].actual_value == Decimal("40.00")
    assert safety[0].threshold_value == Decimal("50.00")
    assert not any(item.alert_type is CashFlowAlertType.CASH_RUPTURE for item in alerts)


def test_detects_date_category_outlier_and_supplier_concentration() -> None:
    supplier_a = UUID("11111111-1111-4111-8111-111111111111")
    supplier_b = UUID("22222222-2222-4222-8222-222222222222")
    items = (
        _item("10.00", date(2026, 11, 2), reference_id=supplier_b),
        _item("10.00", date(2026, 11, 3), reference_id=supplier_a),
        _item("80.00", date(2026, 11, 4), reference_id=supplier_a),
    )
    policy = CashFlowAlertPolicy(outlier_multiplier=Decimal("2.0000"))
    alerts = CashFlowAlertEngine(policy).evaluate(
        _projection(opening="1000.00", reserve="100.00", items=items),
        source=CashFlowAlertSource.PROJECTION,
        exposures=(
            CashFlowExposure(
                supplier_a,
                CashFlowExposureKind.SUPPLIER,
                "SUP-A",
                "Fornecedor A",
            ),
            CashFlowExposure(
                supplier_b,
                CashFlowExposureKind.SUPPLIER,
                "SUP-B",
                "Fornecedor B",
            ),
        ),
    )

    by_type = {item.alert_type for item in alerts}
    assert CashFlowAlertType.DATE_CONCENTRATION in by_type
    assert CashFlowAlertType.DAILY_OUTLIER in by_type
    assert CashFlowAlertType.CATEGORY_CONCENTRATION in by_type
    assert CashFlowAlertType.EXPOSURE_CONCENTRATION in by_type
    supplier_alert = next(
        item
        for item in alerts
        if item.alert_type is CashFlowAlertType.EXPOSURE_CONCENTRATION
    )
    assert supplier_alert.subject_key == "OUTFLOW:SUPPLIER:SUP-A"
    assert supplier_alert.actual_value == Decimal("90.00")
    assert supplier_alert.severity is CashFlowAlertSeverity.CRITICAL
    assert dict(supplier_alert.details)["share"] == "0.9000"


def test_scenario_sensitivity_uses_operational_baseline_without_mutating_it() -> None:
    projection = _projection(
        opening="1000.00",
        reserve="100.00",
        items=(_item("100.00", date(2026, 11, 3)),),
        cost_rate="0.5000",
    )
    policy = CashFlowAlertPolicy(scenario_sensitivity_rate=Decimal("0.0500"))
    alerts = CashFlowAlertEngine(policy).evaluate(
        projection, source=CashFlowAlertSource.SCENARIO
    )
    sensitivity = next(
        item for item in alerts if item.alert_type is CashFlowAlertType.SCENARIO_SENSITIVITY
    )
    assert projection.summary.operational_closing_balance.amount == Decimal("900.00")
    assert projection.summary.scenario_closing_balance.amount == Decimal("850.00")
    assert sensitivity.actual_value == Decimal("50.00")
    assert sensitivity.threshold_value == Decimal("45.00")
    assert sensitivity.severity is CashFlowAlertSeverity.WARNING


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"date_concentration_rate": Decimal("0.0000")}, "between"),
        ({"category_concentration_rate": Decimal("1.0001")}, "between"),
        ({"exposure_concentration_rate": cast(Any, 0.4)}, "finite Decimal"),
        ({"scenario_sensitivity_rate": Decimal("NaN")}, "finite Decimal"),
        ({"outlier_multiplier": Decimal("1.0000")}, "greater than 1"),
        ({"outlier_multiplier": Decimal("101.0000")}, "at most 100"),
        ({"minimum_material_amount": Decimal("0.001")}, "two decimals"),
        ({"minimum_material_amount": Decimal("0.00")}, "positive"),
        ({"minimum_outlier_dates": True}, "between 2 and 365"),
        ({"minimum_outlier_dates": 366}, "between 2 and 365"),
    ],
)
def test_alert_policy_rejects_invalid_thresholds(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        replace(CashFlowAlertPolicy(), **cast(Any, changes))


def test_exposure_and_engine_contracts_are_strict() -> None:
    reference_id = uuid4()
    exposure = CashFlowExposure(
        reference_id,
        CashFlowExposureKind.RUBRIC,
        "  FRETE  ",
        "  Frete contratado  ",
    )
    assert exposure.key == "FRETE"
    assert exposure.label == "Frete contratado"
    with pytest.raises(InvalidCashFlowError, match="unique"):
        CashFlowAlertEngine().evaluate(
            _projection(opening="100.00", reserve="0.00", items=()),
            source=CashFlowAlertSource.PROJECTION,
            exposures=(exposure, exposure),
        )
    with pytest.raises(InvalidCashFlowError, match="immutable tuple"):
        CashFlowAlertEngine().evaluate(
            _projection(opening="100.00", reserve="0.00", items=()),
            source=CashFlowAlertSource.PROJECTION,
            exposures=cast(tuple[CashFlowExposure, ...], []),
        )
    with pytest.raises(InvalidCashFlowError, match="CashFlowAlertSource"):
        CashFlowAlertEngine().evaluate(
            _projection(opening="100.00", reserve="0.00", items=()),
            source=cast(CashFlowAlertSource, "PROJECTION"),
        )


def test_materiality_suppresses_zero_flow_concentration_alerts() -> None:
    alerts = CashFlowAlertEngine().evaluate(
        _projection(opening="100.00", reserve="0.00", items=()),
        source=CashFlowAlertSource.PROJECTION,
    )
    assert not any(
        item.alert_type
        in {
            CashFlowAlertType.DATE_CONCENTRATION,
            CashFlowAlertType.CATEGORY_CONCENTRATION,
            CashFlowAlertType.EXPOSURE_CONCENTRATION,
            CashFlowAlertType.DAILY_OUTLIER,
        }
        for item in alerts
    )

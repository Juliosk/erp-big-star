"""Deterministic liquidity, concentration and sensitivity alert rules."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid5

from erp.modules.finance.domain.cash_flow import (
    CashFlowDirection,
    CashFlowItem,
)
from erp.modules.finance.domain.cash_flow_projection import CashFlowProjection
from erp.modules.finance.domain.exceptions import InvalidCashFlowError

_ALERT_NAMESPACE = UUID("08df0b0d-a8a9-53d4-a1c5-dc4797432094")
_RATE = Decimal("0.0001")
_MONEY = Decimal("0.01")


class CashFlowAlertSource(StrEnum):
    PROJECTION = "PROJECTION"
    SCENARIO = "SCENARIO"


class CashFlowAlertType(StrEnum):
    CASH_RUPTURE = "CASH_RUPTURE"
    SAFETY_THRESHOLD = "SAFETY_THRESHOLD"
    DATE_CONCENTRATION = "DATE_CONCENTRATION"
    CATEGORY_CONCENTRATION = "CATEGORY_CONCENTRATION"
    EXPOSURE_CONCENTRATION = "EXPOSURE_CONCENTRATION"
    DAILY_OUTLIER = "DAILY_OUTLIER"
    SCENARIO_SENSITIVITY = "SCENARIO_SENSITIVITY"


class CashFlowAlertSeverity(StrEnum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class CashFlowAlertDimension(StrEnum):
    OPERATIONAL_BALANCE = "OPERATIONAL_BALANCE"
    SCENARIO_BALANCE = "SCENARIO_BALANCE"
    DATE = "DATE"
    CATEGORY = "CATEGORY"
    RUBRIC = "RUBRIC"
    SUPPLIER = "SUPPLIER"
    BATCH = "BATCH"
    REFERENCE = "REFERENCE"
    SCENARIO = "SCENARIO"


class CashFlowExposureKind(StrEnum):
    RUBRIC = "RUBRIC"
    SUPPLIER = "SUPPLIER"
    BATCH = "BATCH"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True, slots=True)
class CashFlowExposure:
    reference_id: UUID
    kind: CashFlowExposureKind
    key: str
    label: str

    def __post_init__(self) -> None:
        _uuid(self.reference_id, "exposure.reference_id")
        if not isinstance(self.kind, CashFlowExposureKind):
            raise InvalidCashFlowError("exposure.kind must be a CashFlowExposureKind.")
        object.__setattr__(self, "key", _text(self.key, "exposure.key", maximum=120))
        object.__setattr__(self, "label", _text(self.label, "exposure.label", maximum=200))


@dataclass(frozen=True, slots=True)
class CashFlowAlertPolicy:
    """Company-selectable thresholds consumed by the pure engine."""

    date_concentration_rate: Decimal = Decimal("0.5000")
    category_concentration_rate: Decimal = Decimal("0.7000")
    exposure_concentration_rate: Decimal = Decimal("0.4000")
    outlier_multiplier: Decimal = Decimal("2.5000")
    scenario_sensitivity_rate: Decimal = Decimal("0.1000")
    minimum_material_amount: Decimal = Decimal("0.01")
    minimum_outlier_dates: int = 3

    def __post_init__(self) -> None:
        for field_name in (
            "date_concentration_rate",
            "category_concentration_rate",
            "exposure_concentration_rate",
            "scenario_sensitivity_rate",
        ):
            value = _rate(getattr(self, field_name), field_name)
            if not Decimal("0.0001") <= value <= Decimal("1.0000"):
                raise InvalidCashFlowError(f"{field_name} must be between 0.0001 and 1.0000.")
            object.__setattr__(self, field_name, value)
        multiplier = _rate(self.outlier_multiplier, "outlier_multiplier")
        if multiplier <= Decimal("1.0000") or multiplier > Decimal("100.0000"):
            raise InvalidCashFlowError("outlier_multiplier must be greater than 1 and at most 100.")
        object.__setattr__(self, "outlier_multiplier", multiplier)
        if (
            not isinstance(self.minimum_material_amount, Decimal)
            or not self.minimum_material_amount.is_finite()
        ):
            raise InvalidCashFlowError("minimum_material_amount must be a finite Decimal.")
        minimum = self.minimum_material_amount.quantize(_MONEY)
        if minimum != self.minimum_material_amount or minimum <= 0:
            raise InvalidCashFlowError(
                "minimum_material_amount must be positive and use two decimals."
            )
        if type(self.minimum_outlier_dates) is not int or not 2 <= self.minimum_outlier_dates <= 365:
            raise InvalidCashFlowError("minimum_outlier_dates must be between 2 and 365.")

    def snapshot(self) -> dict[str, object]:
        return {
            "date_concentration_rate": str(self.date_concentration_rate),
            "category_concentration_rate": str(self.category_concentration_rate),
            "exposure_concentration_rate": str(self.exposure_concentration_rate),
            "outlier_multiplier": str(self.outlier_multiplier),
            "scenario_sensitivity_rate": str(self.scenario_sensitivity_rate),
            "minimum_material_amount": str(self.minimum_material_amount),
            "minimum_outlier_dates": self.minimum_outlier_dates,
        }


@dataclass(frozen=True, slots=True)
class CashFlowRiskAlert:
    id: UUID
    company_id: UUID
    projection_id: UUID
    projection_version: int
    source: CashFlowAlertSource
    alert_type: CashFlowAlertType
    severity: CashFlowAlertSeverity
    dimension: CashFlowAlertDimension
    subject_key: str
    breach_on: date | None
    actual_value: Decimal
    threshold_value: Decimal
    currency: str
    details: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CashFlowAlertEngine:
    policy: CashFlowAlertPolicy = field(default_factory=CashFlowAlertPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, CashFlowAlertPolicy):
            raise InvalidCashFlowError("policy must be a CashFlowAlertPolicy.")

    def evaluate(
        self,
        projection: CashFlowProjection,
        *,
        source: CashFlowAlertSource,
        exposures: tuple[CashFlowExposure, ...] = (),
    ) -> tuple[CashFlowRiskAlert, ...]:
        if not isinstance(projection, CashFlowProjection):
            raise InvalidCashFlowError("projection must be a CashFlowProjection.")
        if not isinstance(source, CashFlowAlertSource):
            raise InvalidCashFlowError("source must be a CashFlowAlertSource.")
        exposure_index = _exposure_index(exposures)
        alerts = [
            *self._balance_alerts(projection, source),
            *self._date_alerts(projection, source),
            *self._category_alerts(projection, source),
            *self._exposure_alerts(projection, source, exposure_index),
            *self._sensitivity_alerts(projection, source),
        ]
        return tuple(
            sorted(
                alerts,
                key=lambda item: (
                    item.alert_type.value,
                    item.dimension.value,
                    item.breach_on or date.min,
                    item.subject_key,
                ),
            )
        )

    def _balance_alerts(
        self,
        projection: CashFlowProjection,
        source: CashFlowAlertSource,
    ) -> list[CashFlowRiskAlert]:
        alerts: list[CashFlowRiskAlert] = []
        dimensions = (
            (
                "operational",
                CashFlowAlertDimension.OPERATIONAL_BALANCE,
                tuple(
                    (bucket.end_on, bucket.operational_closing_balance.amount)
                    for bucket in projection.buckets
                ),
            ),
            (
                "scenario",
                CashFlowAlertDimension.SCENARIO_BALANCE,
                tuple(
                    (bucket.end_on, bucket.scenario_closing_balance.amount)
                    for bucket in projection.buckets
                ),
            ),
        )
        for subject, dimension, observations in dimensions:
            if source is CashFlowAlertSource.SCENARIO and dimension is CashFlowAlertDimension.OPERATIONAL_BALANCE:
                continue
            for observed_on, balance in observations:
                if balance < 0:
                    alerts.append(
                        self._alert(
                            projection,
                            source=source,
                            alert_type=CashFlowAlertType.CASH_RUPTURE,
                            severity=CashFlowAlertSeverity.CRITICAL,
                            dimension=dimension,
                            subject_key=subject,
                            breach_on=observed_on,
                            actual=balance,
                            threshold=Decimal("0.00"),
                            details=(("balance_kind", subject),),
                        )
                    )
                    break
                if balance < projection.minimum_reserve.amount:
                    alerts.append(
                        self._alert(
                            projection,
                            source=source,
                            alert_type=CashFlowAlertType.SAFETY_THRESHOLD,
                            severity=CashFlowAlertSeverity.CRITICAL,
                            dimension=dimension,
                            subject_key=subject,
                            breach_on=observed_on,
                            actual=balance,
                            threshold=projection.minimum_reserve.amount,
                            details=(("balance_kind", subject),),
                        )
                    )
                    break
        return alerts

    def _date_alerts(
        self,
        projection: CashFlowProjection,
        source: CashFlowAlertSource,
    ) -> list[CashFlowRiskAlert]:
        alerts: list[CashFlowRiskAlert] = []
        for direction in CashFlowDirection:
            daily = _group_items(projection.projected_items, direction, key=lambda item: item.occurs_on)
            total = sum(daily.values(), Decimal("0.00"))
            if total < self.policy.minimum_material_amount:
                continue
            threshold = (total * self.policy.date_concentration_rate).quantize(_MONEY)
            for observed_on, amount in daily.items():
                if amount >= threshold:
                    alerts.append(
                        self._alert(
                            projection,
                            source=source,
                            alert_type=CashFlowAlertType.DATE_CONCENTRATION,
                            severity=_concentration_severity(amount, total),
                            dimension=CashFlowAlertDimension.DATE,
                            subject_key=f"{direction.value}:{observed_on.isoformat()}",
                            breach_on=observed_on,
                            actual=amount,
                            threshold=threshold,
                            details=(("direction", direction.value), ("share", _share(amount, total))),
                        )
                    )
            if len(daily) >= self.policy.minimum_outlier_dates:
                average = total / Decimal(len(daily))
                outlier_threshold = (average * self.policy.outlier_multiplier).quantize(_MONEY)
                for observed_on, amount in daily.items():
                    if amount >= outlier_threshold:
                        alerts.append(
                            self._alert(
                                projection,
                                source=source,
                                alert_type=CashFlowAlertType.DAILY_OUTLIER,
                                severity=CashFlowAlertSeverity.WARNING,
                                dimension=CashFlowAlertDimension.DATE,
                                subject_key=f"{direction.value}:{observed_on.isoformat()}",
                                breach_on=observed_on,
                                actual=amount,
                                threshold=outlier_threshold,
                                details=(("direction", direction.value), ("daily_average", str(average.quantize(_MONEY)))),
                            )
                        )
        return alerts

    def _category_alerts(
        self,
        projection: CashFlowProjection,
        source: CashFlowAlertSource,
    ) -> list[CashFlowRiskAlert]:
        alerts: list[CashFlowRiskAlert] = []
        for direction in CashFlowDirection:
            grouped = _group_items(
                projection.projected_items, direction, key=lambda item: item.category
            )
            total = sum(grouped.values(), Decimal("0.00"))
            if total < self.policy.minimum_material_amount:
                continue
            threshold = (total * self.policy.category_concentration_rate).quantize(_MONEY)
            for category, amount in grouped.items():
                if amount >= threshold:
                    alerts.append(
                        self._alert(
                            projection,
                            source=source,
                            alert_type=CashFlowAlertType.CATEGORY_CONCENTRATION,
                            severity=_concentration_severity(amount, total),
                            dimension=CashFlowAlertDimension.CATEGORY,
                            subject_key=f"{direction.value}:{category.value}",
                            breach_on=None,
                            actual=amount,
                            threshold=threshold,
                            details=(("direction", direction.value), ("category", category.value), ("share", _share(amount, total))),
                        )
                    )
        return alerts

    def _exposure_alerts(
        self,
        projection: CashFlowProjection,
        source: CashFlowAlertSource,
        exposures: dict[UUID, CashFlowExposure],
    ) -> list[CashFlowRiskAlert]:
        alerts: list[CashFlowRiskAlert] = []
        for direction in CashFlowDirection:
            eligible: list[tuple[CashFlowItem, CashFlowExposure]] = []
            for item in projection.projected_items:
                reference_id = item.reference_id
                if (
                    item.direction is direction
                    and reference_id is not None
                    and reference_id in exposures
                ):
                    eligible.append((item, exposures[reference_id]))
            total = sum(
                (
                    item.amount.amount
                    for item in projection.projected_items
                    if item.direction is direction
                ),
                Decimal("0.00"),
            )
            if total < self.policy.minimum_material_amount:
                continue
            grouped: dict[tuple[CashFlowExposureKind, str], Decimal] = defaultdict(
                lambda: Decimal("0.00")
            )
            labels: dict[tuple[CashFlowExposureKind, str], str] = {}
            for item, exposure in eligible:
                identity = (exposure.kind, exposure.key)
                grouped[identity] += item.amount.amount
                labels[identity] = exposure.label
            threshold = (total * self.policy.exposure_concentration_rate).quantize(_MONEY)
            for (kind, key), amount in grouped.items():
                if amount >= threshold:
                    alerts.append(
                        self._alert(
                            projection,
                            source=source,
                            alert_type=CashFlowAlertType.EXPOSURE_CONCENTRATION,
                            severity=_concentration_severity(amount, total),
                            dimension=CashFlowAlertDimension(kind.value),
                            subject_key=f"{direction.value}:{kind.value}:{key}",
                            breach_on=None,
                            actual=amount,
                            threshold=threshold,
                            details=(("direction", direction.value), ("exposure_label", labels[(kind, key)]), ("share", _share(amount, total))),
                        )
                    )
        return alerts

    def _sensitivity_alerts(
        self,
        projection: CashFlowProjection,
        source: CashFlowAlertSource,
    ) -> list[CashFlowRiskAlert]:
        if source is not CashFlowAlertSource.SCENARIO:
            return []
        delta = abs(
            projection.summary.scenario_closing_balance.amount
            - projection.summary.operational_closing_balance.amount
        )
        denominator = max(
            abs(projection.summary.operational_closing_balance.amount),
            projection.minimum_reserve.amount,
            Decimal("1.00"),
        )
        threshold = (denominator * self.policy.scenario_sensitivity_rate).quantize(_MONEY)
        if delta < threshold:
            return []
        return [
            self._alert(
                projection,
                source=source,
                alert_type=CashFlowAlertType.SCENARIO_SENSITIVITY,
                severity=(
                    CashFlowAlertSeverity.CRITICAL
                    if delta >= threshold * 2
                    else CashFlowAlertSeverity.WARNING
                ),
                dimension=CashFlowAlertDimension.SCENARIO,
                subject_key=str(projection.scenario.id),
                breach_on=projection.horizon.end_on,
                actual=delta,
                threshold=threshold,
                details=(("scenario_name", projection.scenario.name), ("sensitivity_share", _share(delta, denominator))),
            )
        ]

    def _alert(
        self,
        projection: CashFlowProjection,
        *,
        source: CashFlowAlertSource,
        alert_type: CashFlowAlertType,
        severity: CashFlowAlertSeverity,
        dimension: CashFlowAlertDimension,
        subject_key: str,
        breach_on: date | None,
        actual: Decimal,
        threshold: Decimal,
        details: tuple[tuple[str, str], ...],
    ) -> CashFlowRiskAlert:
        identity = "|".join(
            (
                str(projection.company_id),
                str(projection.id),
                str(projection.version),
                str(projection.scenario.id),
                source.value,
                alert_type.value,
                dimension.value,
                subject_key,
                breach_on.isoformat() if breach_on is not None else "",
            )
        )
        return CashFlowRiskAlert(
            id=uuid5(_ALERT_NAMESPACE, identity),
            company_id=projection.company_id,
            projection_id=projection.id,
            projection_version=projection.version,
            source=source,
            alert_type=alert_type,
            severity=severity,
            dimension=dimension,
            subject_key=subject_key,
            breach_on=breach_on,
            actual_value=actual.quantize(_MONEY, rounding=ROUND_HALF_UP),
            threshold_value=threshold.quantize(_MONEY, rounding=ROUND_HALF_UP),
            currency=projection.summary.currency,
            details=details,
        )


def _group_items[Key: Hashable](
    items: tuple[CashFlowItem, ...],
    direction: CashFlowDirection,
    *,
    key: Callable[[CashFlowItem], Key],
) -> dict[Key, Decimal]:
    grouped: dict[Key, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for item in items:
        if item.direction is direction:
            grouped[key(item)] += item.amount.amount
    return dict(grouped)


def _exposure_index(exposures: tuple[CashFlowExposure, ...]) -> dict[UUID, CashFlowExposure]:
    if not isinstance(exposures, tuple):
        raise InvalidCashFlowError("exposures must be an immutable tuple.")
    values: dict[UUID, CashFlowExposure] = {}
    for exposure in exposures:
        if not isinstance(exposure, CashFlowExposure):
            raise InvalidCashFlowError("exposures must contain CashFlowExposure values.")
        if exposure.reference_id in values:
            raise InvalidCashFlowError("exposure reference_id values must be unique.")
        values[exposure.reference_id] = exposure
    return values


def _concentration_severity(amount: Decimal, total: Decimal) -> CashFlowAlertSeverity:
    return (
        CashFlowAlertSeverity.CRITICAL
        if amount / total >= Decimal("0.8000")
        else CashFlowAlertSeverity.WARNING
    )


def _share(amount: Decimal, total: Decimal) -> str:
    return str((amount / total).quantize(_RATE, rounding=ROUND_HALF_UP))


def _rate(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidCashFlowError(f"{field_name} must be a finite Decimal.")
    try:
        return value.quantize(_RATE)
    except InvalidOperation as error:
        raise InvalidCashFlowError(f"{field_name} uses unsupported precision.") from error


def _uuid(value: UUID, field_name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidCashFlowError(f"{field_name} must be a non-zero UUID.")
    return value


def _text(value: str, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidCashFlowError(f"{field_name} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidCashFlowError(
            f"{field_name} must contain between 1 and {maximum} characters."
        )
    return normalized


__all__ = [
    "CashFlowAlertDimension",
    "CashFlowAlertEngine",
    "CashFlowAlertPolicy",
    "CashFlowAlertSeverity",
    "CashFlowAlertSource",
    "CashFlowAlertType",
    "CashFlowExposure",
    "CashFlowExposureKind",
    "CashFlowRiskAlert",
]

"""Branch-complete tests for the pure M11 tax-rule foundation."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from erp.modules.fiscal.domain import (
    FiscalFlow,
    InvalidTaxRuleError,
    InvalidTaxRuleTransitionError,
    TaxJurisdiction,
    TaxRateProfile,
    TaxRule,
    TaxRuleCriteria,
    TaxRuleSodViolationError,
    TaxRuleStatus,
)

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
TODAY = date(2026, 11, 11)


def _jurisdiction(**changes: Any) -> TaxJurisdiction:
    values: dict[str, Any] = {
        "country_code": "br",
        "state_code": "sp",
        "municipality_code": "3550308",
    }
    values.update(changes)
    return TaxJurisdiction(**values)


def _criteria(**changes: Any) -> TaxRuleCriteria:
    values: dict[str, Any] = {
        "flow": FiscalFlow.OUTBOUND,
        "ncm": "95030099",
        "cfop": "5102",
        "origin": _jurisdiction(),
        "destination": _jurisdiction(state_code="rj", municipality_code="3304557"),
    }
    values.update(changes)
    return TaxRuleCriteria(**values)


def _rates(**changes: Any) -> TaxRateProfile:
    values: dict[str, Any] = {
        "icms": Decimal("0.1800"),
        "pis": Decimal("0.0165"),
        "cofins": Decimal("0.0760"),
        "ipi": Decimal("0.0000"),
    }
    values.update(changes)
    return TaxRateProfile(**values)


def _rule(**changes: Any) -> TaxRule:
    values: dict[str, Any] = {
        "id": uuid4(),
        "company_id": uuid4(),
        "code": " brinquedos-sp ",
        "version_code": " v1 ",
        "criteria": _criteria(),
        "rates": _rates(),
        "effective_from": TODAY,
        "effective_until": date(2026, 12, 31),
        "created_by": uuid4(),
    }
    values.update(changes)
    return TaxRule(**values)


def test_tax_rule_lifecycle_is_immutable_versioned_and_temporally_bounded() -> None:
    draft = _rule()
    country_only = TaxJurisdiction("br")

    assert draft.code == "BRINQUEDOS-SP"
    assert draft.version_code == "V1"
    assert draft.criteria.origin.country_code == "BR"
    assert draft.criteria.origin.state_code == "SP"
    assert country_only.state_code is None
    assert country_only.municipality_code is None
    assert draft.rates.icms == Decimal("0.1800")
    assert draft.applies_on(TODAY) is False
    with pytest.raises(FrozenInstanceError):
        draft.code = "CHANGED"  # type: ignore[misc]

    active = draft.activate(actor_id=uuid4(), occurred_at=NOW)
    retired = active.retire(occurred_at=NOW + timedelta(days=2))

    assert active.status is TaxRuleStatus.ACTIVE
    assert active.version == 2
    assert active.applies_on(TODAY) is True
    assert active.applies_on(date(2026, 1, 1)) is False
    assert active.applies_on(date(2027, 1, 1)) is False
    assert retired.status is TaxRuleStatus.RETIRED
    assert retired.version == 3
    assert retired.applies_on(TODAY) is False
    assert draft.status is TaxRuleStatus.DRAFT


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"country_code": "BRA"}, "ISO alpha-2"),
        ({"state_code": "S1"}, "two letters"),
        ({"state_code": None, "municipality_code": "3550308"}, "requires state_code"),
        ({"municipality_code": "35503"}, "7 digits"),
    ],
)
def test_tax_jurisdiction_rejects_invalid_geography(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidTaxRuleError, match=message):
        _jurisdiction(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"flow": "OUTBOUND"}, "FiscalFlow"),
        ({"ncm": "9503"}, "8 digits"),
        ({"cfop": "51A2"}, "4 digits"),
        ({"origin": object()}, "TaxJurisdiction"),
    ],
)
def test_tax_rule_criteria_rejects_invalid_classification(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidTaxRuleError, match=message):
        _criteria(**changes)


@pytest.mark.parametrize(
    "value",
    ["0.18", Decimal("NaN"), Decimal("0.18001"), Decimal("1.0001")],
)
def test_tax_rates_require_finite_bounded_four_decimal_values(value: object) -> None:
    with pytest.raises(InvalidTaxRuleError):
        _rates(icms=value)


def test_tax_rate_reports_unsupported_decimal_precision() -> None:
    with pytest.raises(InvalidTaxRuleError, match="unsupported precision"):
        _rates(icms=Decimal("1E+999999999"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": UUID(int=0)}, "non-zero UUID"),
        ({"code": 1}, "must be text"),
        ({"code": "bad code"}, "canonical identifier"),
        ({"version_code": ""}, "canonical identifier"),
        ({"criteria": object()}, "fiscal value objects"),
        ({"rates": object()}, "fiscal value objects"),
        ({"effective_from": "2026-11-11"}, "must be a date"),
        ({"effective_until": date(2026, 1, 1)}, "cannot predate"),
        ({"status": "DRAFT"}, "TaxRuleStatus"),
        ({"version": True}, "positive integer"),
    ],
)
def test_tax_rule_rejects_invalid_root_invariants(
    changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidTaxRuleError, match=message):
        _rule(**changes)


def test_tax_rule_rejects_invalid_transitions_and_actor_evidence() -> None:
    draft = _rule()

    with pytest.raises(TaxRuleSodViolationError):
        draft.activate(actor_id=draft.created_by, occurred_at=NOW)
    with pytest.raises(InvalidTaxRuleError, match="actor_id"):
        draft.activate(actor_id=UUID(int=0), occurred_at=NOW)
    with pytest.raises(InvalidTaxRuleError, match="timezone-aware"):
        draft.activate(actor_id=uuid4(), occurred_at=NOW.replace(tzinfo=None))
    with pytest.raises(InvalidTaxRuleTransitionError):
        draft.retire(occurred_at=NOW)

    active = draft.activate(actor_id=uuid4(), occurred_at=NOW)
    with pytest.raises(InvalidTaxRuleTransitionError):
        active.activate(actor_id=uuid4(), occurred_at=NOW)
    with pytest.raises(InvalidTaxRuleError, match="predate activation"):
        active.retire(occurred_at=NOW - timedelta(seconds=1))
    with pytest.raises(InvalidTaxRuleError, match="value must be a date"):
        active.applies_on("2026-11-11")  # type: ignore[arg-type]


def test_tax_rule_rehydration_rejects_incoherent_lifecycle_evidence() -> None:
    draft = _rule()
    actor = uuid4()

    invalid: list[dict[str, Any]] = [
        {"activated_by": actor},
        {"status": TaxRuleStatus.ACTIVE},
        {
            "status": TaxRuleStatus.ACTIVE,
            "activated_by": UUID(int=0),
            "activated_at": NOW,
        },
        {
            "status": TaxRuleStatus.ACTIVE,
            "activated_by": actor,
            "activated_at": NOW.replace(tzinfo=None),
        },
        {
            "status": TaxRuleStatus.ACTIVE,
            "activated_by": actor,
            "activated_at": NOW,
            "retired_at": NOW,
        },
        {
            "status": TaxRuleStatus.RETIRED,
            "activated_by": actor,
            "activated_at": NOW,
        },
        {
            "status": TaxRuleStatus.RETIRED,
            "activated_by": actor,
            "activated_at": NOW,
            "retired_at": NOW.replace(tzinfo=None),
        },
        {
            "status": TaxRuleStatus.RETIRED,
            "activated_by": actor,
            "activated_at": NOW,
            "retired_at": NOW - timedelta(seconds=1),
        },
    ]

    for changes in invalid:
        with pytest.raises(InvalidTaxRuleError):
            replace(draft, **changes)


def test_open_ended_active_rule_applies_after_start() -> None:
    active = _rule(effective_until=None).activate(actor_id=uuid4(), occurred_at=NOW)

    assert active.applies_on(date(2030, 1, 1)) is True

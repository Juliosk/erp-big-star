"""Defensive branches for the pure M6 validation helpers."""

from decimal import Decimal

import pytest

from erp.modules.procurement.domain import ProcurementDomainError
from erp.modules.procurement.domain.support import currency, identifier, money, text


def test_text_helpers_reject_non_text_values() -> None:
    with pytest.raises(ProcurementDomainError, match="code must be text"):
        identifier(1, "code")  # type: ignore[arg-type]
    with pytest.raises(ProcurementDomainError, match="description must be text"):
        text(1, "description", maximum=10)  # type: ignore[arg-type]
    with pytest.raises(ProcurementDomainError, match="ISO"):
        currency(1)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_money_rejects_non_finite_decimals(value: Decimal) -> None:
    with pytest.raises(ProcurementDomainError, match="must be"):
        money(value, "amount")

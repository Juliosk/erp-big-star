"""Pure accounts-payable segregation-of-duties policy."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from erp.modules.finance.domain.exceptions import (
    InvalidSegregationPolicyError,
    SegregationOfDutiesViolation,
)

_CENT = Decimal("0.01")


def _money(value: Decimal, field: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidSegregationPolicyError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidSegregationPolicyError(
            f"{field} must use supported monetary precision."
        ) from error
    if normalized != value or (normalized < 0 if allow_zero else normalized <= 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise InvalidSegregationPolicyError(
            f"{field} must be {qualifier} with at most two decimal places."
        )
    return normalized


def _actor(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidSegregationPolicyError(f"{field} must be a non-zero UUID.")
    return value


@dataclass(frozen=True, slots=True)
class PayableSegregationPolicy:
    """Require a second actor when a payable reaches the configured threshold."""

    high_value_threshold: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "high_value_threshold",
            _money(self.high_value_threshold, "high_value_threshold"),
        )

    def require_distinct_approver(
        self,
        *,
        created_by: UUID,
        approver_id: UUID,
        amount: Decimal,
    ) -> None:
        creator = _actor(created_by, "created_by")
        approver = _actor(approver_id, "approver_id")
        payable_amount = _money(amount, "amount", allow_zero=True)
        if payable_amount >= self.high_value_threshold and creator == approver:
            raise SegregationOfDutiesViolation(
                "High-value payable provisions require an approver other than the creator."
            )


__all__ = ["PayableSegregationPolicy"]

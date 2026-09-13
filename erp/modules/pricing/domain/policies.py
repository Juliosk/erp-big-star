"""Pricing cost and margin policies owned by M9."""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.pricing.domain.money import Money, Percentage

LEGACY_OPENING = "LEGACY_OPENING"


class PricingPolicyStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def _identifier(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip().upper()
    if not 1 <= len(normalized) <= maximum or re.fullmatch(
        r"[A-Z0-9][A-Z0-9._-]*", normalized
    ) is None:
        raise ValueError(f"{field} must be a canonical identifier of 1 to {maximum} characters.")
    return normalized


@dataclass(frozen=True, slots=True)
class StandardCostSeed:
    id: UUID
    company_id: UUID
    product_id: UUID
    cost: Money
    source: str
    version: int

    def __post_init__(self) -> None:
        if not all(isinstance(value, UUID) for value in (self.id, self.company_id, self.product_id)):
            raise ValueError("standard cost seed identities must be UUIDs.")
        if self.source != LEGACY_OPENING:
            raise ValueError("initial M9 standard cost source must be LEGACY_OPENING.")
        if self.cost.currency != "BRL":
            raise ValueError("initial M9 standard cost supports BRL only.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls, *, company_id: UUID, product_id: UUID, cost: Money
    ) -> StandardCostSeed:
        return cls(
            id=uuid4(),
            company_id=company_id,
            product_id=product_id,
            cost=cost,
            source=LEGACY_OPENING,
            version=1,
        )


@dataclass(frozen=True, slots=True)
class MinimumMarginPolicy:
    id: UUID
    company_id: UUID
    code: str
    name: str
    minimum_margin: Percentage
    status: PricingPolicyStatus
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise ValueError("minimum-margin policy identity and company scope must be UUIDs.")
        _identifier(self.code, field="code", maximum=64)
        if not 1 <= len(self.name) <= 160 or self.name != self.name.strip():
            raise ValueError("name must contain 1 to 160 trimmed characters.")
        if not isinstance(self.status, PricingPolicyStatus):
            raise ValueError("status must be an official pricing policy status.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        name: str,
        minimum_margin: Percentage,
    ) -> MinimumMarginPolicy:
        return cls(
            id=uuid4(),
            company_id=company_id,
            code=_identifier(code, field="code", maximum=64),
            name=name.strip(),
            minimum_margin=minimum_margin,
            status=PricingPolicyStatus.ACTIVE,
            version=1,
        )


def profitability_margin(*, price: Money, cost: Money) -> Percentage:
    if price.currency != cost.currency:
        raise ValueError("price and cost currencies must match.")
    if price.amount <= 0:
        raise ValueError("price must be greater than zero for profitability checks.")
    if cost.amount > price.amount:
        raise ValueError("cost cannot be above price.")
    return Percentage.ratio((price.amount - cost.amount) / price.amount)


def ensure_minimum_margin(
    *,
    price: Money,
    cost: StandardCostSeed,
    policy: MinimumMarginPolicy | None,
) -> Percentage:
    actual = profitability_margin(price=price, cost=cost.cost)
    if policy is not None and actual.value < policy.minimum_margin.value:
        raise ValueError(
            "price does not satisfy the active minimum margin policy "
            f"({actual.value:.4f} < {policy.minimum_margin.value:.4f})."
        )
    return actual


__all__ = [
    "LEGACY_OPENING",
    "MinimumMarginPolicy",
    "PricingPolicyStatus",
    "StandardCostSeed",
    "ensure_minimum_margin",
    "profitability_margin",
]

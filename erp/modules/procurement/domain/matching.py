"""Pure M6 three-way matching value objects and deterministic rules."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Self
from uuid import UUID

from erp.modules.procurement.domain.exceptions import (
    InvalidMatchingLineError,
    InvalidMatchingToleranceError,
    MatchingScopeError,
)

_PERCENT_QUANTUM = Decimal("0.0001")
_QUANTITY_QUANTUM = Decimal("0.000001")
_MONEY_QUANTUM = Decimal("0.000001")
_ROUNDING_QUANTUM = Decimal("0.01")
_MAX_ROUNDING_LIMIT = Decimal("1.00")


class MatchStatus(StrEnum):
    """Stable result vocabulary for a line or complete three-way match."""

    MATCHED = "MATCHED"
    TOLERANCE_EXCEEDED = "TOLERANCE_EXCEEDED"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"


@dataclass(frozen=True, slots=True)
class MatchingTolerancePolicy:
    """Tenant-bound tolerance snapshot used for one deterministic comparison."""

    company_id: UUID
    unit_price_variance_percentage: Decimal
    quantity_variance_percentage: Decimal
    rounding_absolute_limit: Decimal
    version: int = 1

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        unit_price_variance_percentage: Decimal | str | int = Decimal("0"),
        quantity_variance_percentage: Decimal | str | int = Decimal("0"),
        rounding_absolute_limit: Decimal | str | int = Decimal("0.01"),
        version: int = 1,
    ) -> Self:
        return cls(
            company_id=company_id,
            unit_price_variance_percentage=_percentage(
                unit_price_variance_percentage, "unit_price_variance_percentage"
            ),
            quantity_variance_percentage=_percentage(
                quantity_variance_percentage, "quantity_variance_percentage"
            ),
            rounding_absolute_limit=_rounding_limit(rounding_absolute_limit),
            version=version,
        )

    def __post_init__(self) -> None:
        _uuid(self.company_id, "company_id", InvalidMatchingToleranceError)
        object.__setattr__(
            self,
            "unit_price_variance_percentage",
            _percentage(self.unit_price_variance_percentage, "unit_price_variance_percentage"),
        )
        object.__setattr__(
            self,
            "quantity_variance_percentage",
            _percentage(self.quantity_variance_percentage, "quantity_variance_percentage"),
        )
        object.__setattr__(
            self,
            "rounding_absolute_limit",
            _rounding_limit(self.rounding_absolute_limit),
        )
        if type(self.version) is not int or self.version < 1:
            raise InvalidMatchingToleranceError("version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class ThreeWayMatchReferences:
    """Immutable cross-context identities; never an imported foreign aggregate."""

    company_id: UUID
    purchase_order_id: UUID
    goods_receipt_ids: tuple[UUID, ...]
    inbound_fiscal_document_ids: tuple[UUID, ...]
    provisional_entry_id: UUID
    payable_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        purchase_order_id: UUID,
        goods_receipt_ids: tuple[UUID, ...],
        inbound_fiscal_document_ids: tuple[UUID, ...],
        provisional_entry_id: UUID,
        payable_id: UUID | None = None,
    ) -> Self:
        return cls(
            company_id=company_id,
            purchase_order_id=purchase_order_id,
            goods_receipt_ids=goods_receipt_ids,
            inbound_fiscal_document_ids=inbound_fiscal_document_ids,
            provisional_entry_id=provisional_entry_id,
            payable_id=payable_id,
        )

    def __post_init__(self) -> None:
        for field, value in (
            ("company_id", self.company_id),
            ("purchase_order_id", self.purchase_order_id),
            ("provisional_entry_id", self.provisional_entry_id),
        ):
            _uuid(value, field, InvalidMatchingLineError)
        if self.payable_id is not None:
            _uuid(self.payable_id, "payable_id", InvalidMatchingLineError)
        _unique_uuid_tuple(self.goods_receipt_ids, "goods_receipt_ids")
        _unique_uuid_tuple(self.inbound_fiscal_document_ids, "inbound_fiscal_document_ids")


@dataclass(frozen=True, slots=True)
class ThreeWayMatchLine:
    """One immutable PO/receipt/invoice line snapshot used by the M6 owner."""

    company_id: UUID
    match_key: str
    purchase_order_item_id: UUID
    goods_receipt_item_id: UUID
    fiscal_document_item_id: UUID
    ordered_quantity: Decimal
    received_quantity: Decimal
    invoiced_quantity: Decimal
    ordered_unit_price: Decimal
    invoiced_unit_price: Decimal
    currency: str

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        match_key: str,
        purchase_order_item_id: UUID,
        goods_receipt_item_id: UUID,
        fiscal_document_item_id: UUID,
        ordered_quantity: Decimal | str | int,
        received_quantity: Decimal | str | int,
        invoiced_quantity: Decimal | str | int,
        ordered_unit_price: Decimal | str | int,
        invoiced_unit_price: Decimal | str | int,
        currency: str,
    ) -> Self:
        return cls(
            company_id=company_id,
            match_key=match_key,
            purchase_order_item_id=purchase_order_item_id,
            goods_receipt_item_id=goods_receipt_item_id,
            fiscal_document_item_id=fiscal_document_item_id,
            ordered_quantity=_positive_decimal(
                ordered_quantity, "ordered_quantity", _QUANTITY_QUANTUM
            ),
            received_quantity=_non_negative_decimal(
                received_quantity, "received_quantity", _QUANTITY_QUANTUM
            ),
            invoiced_quantity=_positive_decimal(
                invoiced_quantity, "invoiced_quantity", _QUANTITY_QUANTUM
            ),
            ordered_unit_price=_non_negative_decimal(
                ordered_unit_price, "ordered_unit_price", _MONEY_QUANTUM
            ),
            invoiced_unit_price=_non_negative_decimal(
                invoiced_unit_price, "invoiced_unit_price", _MONEY_QUANTUM
            ),
            currency=currency,
        )

    def __post_init__(self) -> None:
        for field, value in (
            ("company_id", self.company_id),
            ("purchase_order_item_id", self.purchase_order_item_id),
            ("goods_receipt_item_id", self.goods_receipt_item_id),
            ("fiscal_document_item_id", self.fiscal_document_item_id),
        ):
            _uuid(value, field, InvalidMatchingLineError)
        object.__setattr__(self, "match_key", _match_key(self.match_key))
        object.__setattr__(
            self,
            "ordered_quantity",
            _positive_decimal(self.ordered_quantity, "ordered_quantity", _QUANTITY_QUANTUM),
        )
        object.__setattr__(
            self,
            "received_quantity",
            _non_negative_decimal(self.received_quantity, "received_quantity", _QUANTITY_QUANTUM),
        )
        object.__setattr__(
            self,
            "invoiced_quantity",
            _positive_decimal(self.invoiced_quantity, "invoiced_quantity", _QUANTITY_QUANTUM),
        )
        object.__setattr__(
            self,
            "ordered_unit_price",
            _non_negative_decimal(self.ordered_unit_price, "ordered_unit_price", _MONEY_QUANTUM),
        )
        object.__setattr__(
            self,
            "invoiced_unit_price",
            _non_negative_decimal(self.invoiced_unit_price, "invoiced_unit_price", _MONEY_QUANTUM),
        )
        object.__setattr__(self, "currency", _currency(self.currency))


@dataclass(frozen=True, slots=True)
class LineMatchResult:
    """Explainable result for one compared line."""

    line: ThreeWayMatchLine
    status: MatchStatus
    quantity_delta: Decimal
    unit_price_delta: Decimal
    allowed_quantity_delta: Decimal
    allowed_unit_price_delta: Decimal
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ThreeWayMatchReport:
    """Aggregate result calculated exclusively from immutable snapshots."""

    company_id: UUID
    policy: MatchingTolerancePolicy
    lines: tuple[LineMatchResult, ...]
    status: MatchStatus

    @property
    def matched(self) -> bool:
        return self.status is MatchStatus.MATCHED


def compare_line(line: ThreeWayMatchLine, policy: MatchingTolerancePolicy) -> LineMatchResult:
    """Compare physical/fiscal quantity and PO/fiscal unit price."""
    if not isinstance(line, ThreeWayMatchLine):
        raise InvalidMatchingLineError("line must be a ThreeWayMatchLine.")
    if not isinstance(policy, MatchingTolerancePolicy):
        raise InvalidMatchingToleranceError("policy must be a MatchingTolerancePolicy.")
    if line.company_id != policy.company_id:
        raise MatchingScopeError("line and tolerance policy must belong to the same company.")

    quantity_delta = line.received_quantity - line.invoiced_quantity
    unit_price_delta = line.invoiced_unit_price - line.ordered_unit_price
    allowed_quantity = line.invoiced_quantity * policy.quantity_variance_percentage / Decimal("100")
    percentage_price = (
        line.ordered_unit_price * policy.unit_price_variance_percentage / Decimal("100")
    )
    allowed_price = max(percentage_price, policy.rounding_absolute_limit)
    quantity_mismatch = abs(quantity_delta) > allowed_quantity
    price_mismatch = abs(unit_price_delta) > allowed_price

    if quantity_mismatch and price_mismatch:
        status = MatchStatus.TOLERANCE_EXCEEDED
    elif quantity_mismatch:
        status = MatchStatus.QUANTITY_MISMATCH
    elif price_mismatch:
        status = MatchStatus.PRICE_MISMATCH
    else:
        status = MatchStatus.MATCHED

    reasons = tuple(
        reason
        for exceeded, reason in (
            (quantity_mismatch, "QUANTITY_TOLERANCE_EXCEEDED"),
            (price_mismatch, "UNIT_PRICE_TOLERANCE_EXCEEDED"),
        )
        if exceeded
    )
    return LineMatchResult(
        line=line,
        status=status,
        quantity_delta=quantity_delta,
        unit_price_delta=unit_price_delta,
        allowed_quantity_delta=allowed_quantity,
        allowed_unit_price_delta=allowed_price,
        reasons=reasons,
    )


def compare_lines(
    lines: tuple[ThreeWayMatchLine, ...], policy: MatchingTolerancePolicy
) -> ThreeWayMatchReport:
    """Compare a unique set of lines and derive the aggregate blocking status."""
    if not isinstance(lines, tuple) or not lines:
        raise InvalidMatchingLineError("lines must be a non-empty tuple.")
    if any(not isinstance(line, ThreeWayMatchLine) for line in lines):
        raise InvalidMatchingLineError("every line must be a ThreeWayMatchLine.")
    keys = tuple(line.match_key for line in lines)
    if len(set(keys)) != len(keys):
        raise InvalidMatchingLineError("match_key must be unique inside a match report.")

    results = tuple(compare_line(line, policy) for line in lines)
    statuses = {result.status for result in results}
    if (
        MatchStatus.TOLERANCE_EXCEEDED in statuses
        or {
            MatchStatus.QUANTITY_MISMATCH,
            MatchStatus.PRICE_MISMATCH,
        }
        <= statuses
    ):
        status = MatchStatus.TOLERANCE_EXCEEDED
    elif MatchStatus.QUANTITY_MISMATCH in statuses:
        status = MatchStatus.QUANTITY_MISMATCH
    elif MatchStatus.PRICE_MISMATCH in statuses:
        status = MatchStatus.PRICE_MISMATCH
    else:
        status = MatchStatus.MATCHED
    return ThreeWayMatchReport(policy.company_id, policy, results, status)


def _uuid(value: object, field: str, error_type: type[ValueError]) -> UUID:
    if not isinstance(value, UUID):
        raise error_type(f"{field} must be a UUID.")
    return value


def _decimal(
    value: Decimal | str | int,
    field: str,
    quantum: Decimal,
    error_type: type[ValueError],
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise error_type(f"{field} must be a valid decimal.") from error
    if not parsed.is_finite():
        raise error_type(f"{field} must be finite.")
    try:
        return parsed.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise error_type(f"{field} must be a valid decimal.") from error


def _percentage(value: Decimal | str | int, field: str) -> Decimal:
    normalized = _decimal(value, field, _PERCENT_QUANTUM, InvalidMatchingToleranceError)
    if not Decimal("0") <= normalized <= Decimal("100"):
        raise InvalidMatchingToleranceError(f"{field} must be between 0 and 100.")
    return normalized


def _rounding_limit(value: Decimal | str | int) -> Decimal:
    normalized = _decimal(
        value,
        "rounding_absolute_limit",
        _ROUNDING_QUANTUM,
        InvalidMatchingToleranceError,
    )
    if not Decimal("0") <= normalized <= _MAX_ROUNDING_LIMIT:
        raise InvalidMatchingToleranceError(
            "rounding_absolute_limit must be between 0.00 and 1.00."
        )
    return normalized


def _positive_decimal(value: Decimal | str | int, field: str, quantum: Decimal) -> Decimal:
    normalized = _decimal(value, field, quantum, InvalidMatchingLineError)
    if normalized <= 0:
        raise InvalidMatchingLineError(f"{field} must be positive.")
    return normalized


def _non_negative_decimal(value: Decimal | str | int, field: str, quantum: Decimal) -> Decimal:
    normalized = _decimal(value, field, quantum, InvalidMatchingLineError)
    if normalized < 0:
        raise InvalidMatchingLineError(f"{field} cannot be negative.")
    return normalized


def _match_key(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidMatchingLineError("match_key must be text.")
    normalized = value.strip().upper()
    if not 1 <= len(normalized) <= 64 or re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", normalized) is None:
        raise InvalidMatchingLineError("match_key must be a canonical identifier.")
    return normalized


def _currency(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value.strip().upper()) is None:
        raise InvalidMatchingLineError("currency must use ISO 4217 alpha-3 format.")
    return value.strip().upper()


def _unique_uuid_tuple(values: tuple[UUID, ...], field: str) -> None:
    if not isinstance(values, tuple) or not values:
        raise InvalidMatchingLineError(f"{field} must be a non-empty tuple.")
    if any(not isinstance(value, UUID) for value in values):
        raise InvalidMatchingLineError(f"every {field} member must be a UUID.")
    if len(set(values)) != len(values):
        raise InvalidMatchingLineError(f"{field} members must be unique.")


__all__ = [
    "LineMatchResult",
    "MatchStatus",
    "MatchingTolerancePolicy",
    "ThreeWayMatchLine",
    "ThreeWayMatchReferences",
    "ThreeWayMatchReport",
    "compare_line",
    "compare_lines",
]

"""Pure validation helpers for the M15 domain."""

import re
from decimal import Decimal, InvalidOperation
from uuid import UUID


def require_uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError(f"{field} must be a UUID.")
    return value


def identifier(value: str, field: str, *, maximum: int = 64) -> str:
    normalized = value.strip().upper()
    if (
        not 1 <= len(normalized) <= maximum
        or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*", normalized) is None
    ):
        raise ValueError(
            f"{field} must be a canonical identifier of 1 to {maximum} characters."
        )
    return normalized


def quantity(value: Decimal | str | int) -> Decimal:
    try:
        normalized = Decimal(value).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("quantity must be a valid decimal.") from error
    if normalized <= 0:
        raise ValueError("quantity must be positive.")
    return normalized


def money(value: Decimal | str | int, field: str) -> Decimal:
    try:
        normalized = Decimal(value).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be a valid monetary amount.") from error
    if normalized < 0:
        raise ValueError(f"{field} cannot be negative.")
    return normalized


__all__ = ["identifier", "money", "quantity", "require_uuid"]

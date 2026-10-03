"""Small framework-free validation helpers shared by M6 aggregates."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from erp.modules.procurement.domain.exceptions import ProcurementDomainError


def require_uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ProcurementDomainError(f"{field} must be a UUID.")
    return value


def identifier(value: str, field: str, *, maximum: int = 64) -> str:
    if not isinstance(value, str):
        raise ProcurementDomainError(f"{field} must be text.")
    normalized = value.strip().upper()
    if (
        not 1 <= len(normalized) <= maximum
        or re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", normalized) is None
    ):
        raise ProcurementDomainError(
            f"{field} must be a canonical identifier of 1 to {maximum} characters."
        )
    return normalized


def text(value: str, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ProcurementDomainError(f"{field} must be text.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= maximum:
        raise ProcurementDomainError(f"{field} must contain 1 to {maximum} characters.")
    return normalized


def quantity(value: Decimal | str | int) -> Decimal:
    normalized = _decimal(value, "quantity", Decimal("0.000001"))
    if normalized <= 0:
        raise ProcurementDomainError("quantity must be positive.")
    return normalized


def money(value: Decimal | str | int, field: str) -> Decimal:
    normalized = _decimal(value, field, Decimal("0.01"))
    if normalized < 0:
        raise ProcurementDomainError(f"{field} cannot be negative.")
    return normalized


def currency(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value.strip().upper()) is None:
        raise ProcurementDomainError("currency must use ISO 4217 alpha-3 format.")
    return value.strip().upper()


def _decimal(value: Decimal | str | int, field: str, quantum: Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as error:
        raise ProcurementDomainError(f"{field} must be a valid decimal.") from error
    if not normalized.is_finite():
        raise ProcurementDomainError(f"{field} must be finite.")
    return normalized


__all__ = ["currency", "identifier", "money", "quantity", "require_uuid", "text"]

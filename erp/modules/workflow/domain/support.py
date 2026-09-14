"""Shared pure validation helpers for M22 Workflow."""

from decimal import Decimal, InvalidOperation
from uuid import UUID


def require_uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError(f"{field} must be a UUID.")
    return value


def normalize_code(value: str, field: str = "code", *, max_length: int = 64) -> str:
    code = value.strip().upper()
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if (
        not code
        or len(code) > max_length
        or not code[0].isalnum()
        or any(char not in allowed for char in code)
    ):
        raise ValueError(f"{field} must use uppercase alphanumeric code format.")
    return code


def normalize_text(value: str, field: str, *, max_length: int = 200) -> str:
    text = value.strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} must be 1-{max_length} characters.")
    return text


def normalize_amount(value: Decimal | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("amount must be a decimal value.") from error
    if amount < 0:
        raise ValueError("amount must be non-negative.")
    return amount


__all__ = ["normalize_amount", "normalize_code", "normalize_text", "require_uuid"]

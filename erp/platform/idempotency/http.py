"""FastAPI boundary helper for mandatory command idempotency keys."""

from typing import Annotated

from fastapi import Header

from erp.platform.errors import ApplicationError


async def require_idempotency_key(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> str:
    """Normalize the mandatory header and reject whitespace-only values."""
    normalized = idempotency_key.strip()
    if not normalized:
        raise ApplicationError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="Idempotency-Key must not be blank.",
            status_code=400,
        )
    return normalized


__all__ = ["require_idempotency_key"]

"""Internal persistence guards; authorization and transactions remain with the caller."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.errors import ApplicationError


def require_write_scope(company_id: UUID, selected_company: UUID, actor_id: UUID) -> None:
    if company_id != selected_company:
        raise ApplicationError(
            code="SCOPE_FORBIDDEN",
            message="Import metadata is outside the selected company.",
            status_code=403,
        )
    if not isinstance(actor_id, UUID):
        raise ValueError("An explicit actor UUID is required.")


def require_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


async def flush_insert(session: AsyncSession, *, conflict_code: str) -> None:
    try:
        await session.flush()
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise ApplicationError(
                code=conflict_code,
                message="Import identifier or version already exists.",
                status_code=409,
            ) from error
        raise

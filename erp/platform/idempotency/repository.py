"""PostgreSQL adapter for concurrency-safe idempotency keys."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.idempotency.models import IdempotencyRecordModel, IdempotencyStatus


class IdempotencyRepository:
    """Use a unique constraint as the authority for command ownership."""

    async def insert_processing(
        self,
        session: AsyncSession,
        *,
        scope: str,
        operation: str,
        key: str,
        request_hash: str,
        expires_at: datetime,
    ) -> UUID | None:
        """Claim a new scoped key, returning None when it already exists."""
        record_id = uuid4()
        statement = (
            insert(IdempotencyRecordModel)
            .values(
                id=record_id,
                scope=scope,
                operation=operation,
                idempotency_key=key,
                request_hash=request_hash,
                status=IdempotencyStatus.PROCESSING,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=["scope", "operation", "idempotency_key"])
            .returning(IdempotencyRecordModel.id)
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def get_locked(
        self,
        session: AsyncSession,
        *,
        scope: str,
        operation: str,
        key: str,
    ) -> IdempotencyRecordModel:
        """Lock an existing key while its reuse decision is made."""
        result = await session.scalars(
            select(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.scope == scope,
                IdempotencyRecordModel.operation == operation,
                IdempotencyRecordModel.idempotency_key == key,
            )
            .with_for_update()
        )
        return result.one()

    async def complete(
        self,
        session: AsyncSession,
        *,
        record_id: UUID,
        response_status: int,
        response_body: dict[str, object],
        completed_at: datetime,
    ) -> None:
        """Attach the exact public result to a successfully completed command."""
        await session.execute(
            update(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.id == record_id,
                IdempotencyRecordModel.status == IdempotencyStatus.PROCESSING,
            )
            .values(
                status=IdempotencyStatus.COMPLETED,
                response_status=response_status,
                response_body=response_body,
                completed_at=completed_at,
            )
        )


__all__ = ["IdempotencyRepository"]

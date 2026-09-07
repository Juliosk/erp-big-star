"""PostgreSQL adapter for safe batched Outbox publication."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.outbox.models import OutboxEventModel


class OutboxRepository:
    """Stage, claim and finalize Outbox records in caller-owned transactions."""

    async def add(self, session: AsyncSession, event: OutboxEventModel) -> None:
        """Stage one event in the same transaction as its business change."""
        session.add(event)
        await session.flush()

    async def claim_pending(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[OutboxEventModel]:
        """Lock a bounded batch without blocking competing publisher workers."""
        statement: Select[tuple[OutboxEventModel]] = (
            select(OutboxEventModel)
            .where(OutboxEventModel.published_at.is_(None))
            .order_by(OutboxEventModel.occurred_at, OutboxEventModel.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await session.scalars(statement)
        return list(result)

    async def claim_by_event_id(
        self,
        session: AsyncSession,
        event_id: UUID,
    ) -> OutboxEventModel | None:
        """Lock one still-pending event for deterministic acceptance workflows."""
        result = await session.scalars(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.event_id == event_id,
                OutboxEventModel.published_at.is_(None),
            )
            .with_for_update(skip_locked=True)
        )
        return result.one_or_none()

    async def get_by_event_id(
        self,
        session: AsyncSession,
        event_id: UUID,
    ) -> OutboxEventModel | None:
        """Read one record by the globally unique message identity."""
        result = await session.scalars(
            select(OutboxEventModel).where(OutboxEventModel.event_id == event_id)
        )
        return result.one_or_none()

    def mark_published(self, event: OutboxEventModel, *, published_at: datetime) -> None:
        """Finalize a broker-confirmed publication."""
        event.published_at = published_at
        event.publish_attempts += 1
        event.last_error = None

    def mark_failed(self, event: OutboxEventModel, *, error_summary: str) -> None:
        """Record a safe failure summary for a future retry."""
        event.publish_attempts += 1
        event.last_error = error_summary[:2000]


__all__ = ["OutboxRepository"]

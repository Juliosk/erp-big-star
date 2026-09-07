"""PostgreSQL adapter for atomic Inbox reservations."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.inbox.models import InboxEventModel, InboxStatus
from erp.platform.messaging import MessageEnvelope


@dataclass(frozen=True, slots=True)
class InboxReservation:
    """Outcome of atomically claiming one message for one consumer."""

    inbox_id: UUID
    duplicate: bool


class InboxRepository:
    """Enforce consumer/message uniqueness at the PostgreSQL boundary."""

    async def reserve(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        envelope: MessageEnvelope,
    ) -> InboxReservation:
        """Insert once, using the database constraint as the concurrency authority."""
        inbox_id = uuid4()
        statement = (
            insert(InboxEventModel)
            .values(
                id=inbox_id,
                consumer_name=consumer_name,
                event_id=envelope.message_id,
                event_type=envelope.message_type,
                event_version=envelope.event_version,
                status=InboxStatus.PROCESSING,
                attempts=1,
            )
            .on_conflict_do_nothing(index_elements=["consumer_name", "event_id"])
            .returning(InboxEventModel.id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is not None:
            return InboxReservation(inbox_id=inserted, duplicate=False)

        duplicate_statement = (
            update(InboxEventModel)
            .where(
                InboxEventModel.consumer_name == consumer_name,
                InboxEventModel.event_id == envelope.message_id,
            )
            .values(attempts=InboxEventModel.attempts + 1)
            .returning(InboxEventModel.id)
        )
        existing = (await session.execute(duplicate_statement)).scalar_one()
        return InboxReservation(inbox_id=existing, duplicate=True)

    async def mark_processed(
        self,
        session: AsyncSession,
        reservation: InboxReservation,
        *,
        processed_at: datetime,
    ) -> None:
        """Mark success only after the local effect has completed."""
        await session.execute(
            update(InboxEventModel)
            .where(InboxEventModel.id == reservation.inbox_id)
            .values(
                status=InboxStatus.PROCESSED,
                processed_at=processed_at,
                last_error=None,
            )
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        event_id: UUID,
    ) -> InboxEventModel | None:
        """Read one receipt for diagnostics and tests."""
        result = await session.scalars(
            select(InboxEventModel).where(
                InboxEventModel.consumer_name == consumer_name,
                InboxEventModel.event_id == event_id,
            )
        )
        return result.one_or_none()

    async def mark_failed(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        event_id: UUID,
        error_summary: str,
    ) -> None:
        """Record an operational failure in a separate post-rollback transaction."""
        await session.execute(
            update(InboxEventModel)
            .where(
                InboxEventModel.consumer_name == consumer_name,
                InboxEventModel.event_id == event_id,
            )
            .values(
                status=InboxStatus.FAILED,
                last_error=error_summary[:2000],
                attempts=InboxEventModel.attempts + 1,
                processed_at=None,
                received_at=func.now(),
            )
        )


__all__ = ["InboxRepository", "InboxReservation"]

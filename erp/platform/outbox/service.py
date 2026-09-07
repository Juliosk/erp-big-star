"""Application service for transactional event staging."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox.models import OutboxEventModel
from erp.platform.outbox.repository import OutboxRepository


class OutboxService:
    """Write a complete message envelope without owning the transaction commit."""

    def __init__(self, repository: OutboxRepository | None = None) -> None:
        self._repository = repository or OutboxRepository()

    async def enqueue(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
        *,
        headers: dict[str, Any] | None = None,
    ) -> UUID:
        """Stage the envelope beside the originating business mutation."""
        model = OutboxEventModel(
            event_id=envelope.message_id,
            event_type=envelope.message_type,
            event_version=envelope.event_version,
            aggregate_type=envelope.aggregate_type,
            aggregate_id=envelope.aggregate_id,
            source_module=envelope.producer_module,
            occurred_at=envelope.occurred_at,
            payload=envelope.model_dump(mode="json"),
            headers=headers or {},
            correlation_id=envelope.correlation_id,
            causation_id=envelope.causation_id,
            request_id=envelope.request_id,
        )
        await self._repository.add(session, model)
        return model.id


__all__ = ["OutboxService"]

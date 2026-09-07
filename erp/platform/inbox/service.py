"""Transaction-neutral orchestration for idempotent consumers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.inbox.repository import InboxRepository
from erp.platform.messaging import MessageEnvelope

type InboxEffect = Callable[[AsyncSession, MessageEnvelope], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class InboxProcessResult:
    """Consumer outcome used to decide whether transport ACK is safe."""

    duplicate: bool
    processed: bool


class InboxService:
    """Run an effect once and complete Inbox state in that same transaction."""

    def __init__(self, repository: InboxRepository | None = None) -> None:
        self._repository = repository or InboxRepository()

    async def process(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        envelope: MessageEnvelope,
        effect: InboxEffect,
    ) -> InboxProcessResult:
        """Reserve, execute and mark processed without committing the transaction."""
        reservation = await self._repository.reserve(
            session,
            consumer_name=consumer_name,
            envelope=envelope,
        )
        if reservation.duplicate:
            return InboxProcessResult(duplicate=True, processed=False)

        await effect(session, envelope)
        await self._repository.mark_processed(
            session,
            reservation,
            processed_at=datetime.now(UTC),
        )
        return InboxProcessResult(duplicate=False, processed=True)


__all__ = ["InboxEffect", "InboxProcessResult", "InboxService"]

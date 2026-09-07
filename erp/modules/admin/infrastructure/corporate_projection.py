"""Idempotent corporate event projection owned by M1."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base, Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope

CORPORATE_PROJECTOR = "admin.corporate-projector.v1"
SUPPORTED_EVENTS = {
    "CompanyCreated": "company",
    "CompanyUpdated": "company",
    "BranchCreated": "branch",
    "BranchUpdated": "branch",
}


class CorporateEventProjectionModel(Base):
    """Controlled read model proving durable M1 event consumption."""

    __tablename__ = "corporate_event_projection"
    __table_args__ = (
        Index("ix_corporate_projection_company", "company_id", "projected_at"),
        Index("ix_corporate_projection_branch", "branch_id", "projected_at"),
        {"schema": "admin"},
    )

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    message_type: Mapped[str] = mapped_column(String(150), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(nullable=False)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    projected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CorporateProjectionConsumer:
    """Project supported events exactly once using Inbox in the same transaction."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        expected_aggregate = SUPPORTED_EVENTS.get(envelope.message_type)
        if (
            expected_aggregate is None
            or envelope.event_version != 1
            or envelope.aggregate_type != expected_aggregate
            or envelope.aggregate_version is None
            or envelope.company_id is None
        ):
            raise ValueError("Unsupported corporate event envelope.")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            session.add(
                CorporateEventProjectionModel(
                    event_id=message.message_id,
                    message_type=message.message_type,
                    aggregate_type=message.aggregate_type,
                    aggregate_id=message.aggregate_id,
                    aggregate_version=message.aggregate_version,
                    company_id=message.company_id,
                    branch_id=message.branch_id,
                    payload=message.payload,
                )
            )
            await session.flush()

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=CORPORATE_PROJECTOR,
                envelope=envelope,
                effect=effect,
            )


__all__ = [
    "CORPORATE_PROJECTOR",
    "SUPPORTED_EVENTS",
    "CorporateEventProjectionModel",
    "CorporateProjectionConsumer",
]

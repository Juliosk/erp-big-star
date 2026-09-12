"""Idempotent M5 movement projection fed by domain events."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base, Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope

INVENTORY_MOVEMENT_PROJECTOR = "inventory.movement-projector.v1"
INVENTORY_ADJUSTED = "InventoryAdjusted"
SUPPORTED_EVENTS = {INVENTORY_ADJUSTED}


class InventoryMovementProjectionModel(Base):
    """Event-keyed async trace for inventory movements consumed through Inbox."""

    __tablename__ = "inventory_movement_projection"
    __table_args__ = (
        Index("ix_inventory_movement_projection_company", "company_id", "projected_at"),
        Index("ix_inventory_movement_projection_transaction", "company_id", "transaction_id"),
        CheckConstraint("aggregate_version >= 1", name="version_positive"),
        CheckConstraint("posting_count >= 1", name="posting_count_positive"),
        {"schema": "inventory"},
    )

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    message_type: Mapped[str] = mapped_column(String(150), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(nullable=False)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    posting_count: Mapped[int] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    projected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class InventoryMovementProjectionConsumer:
    """Project supported M5 events exactly once using Inbox in the same transaction."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        if (
            envelope.message_type not in SUPPORTED_EVENTS
            or envelope.event_version != 1
            or envelope.producer_module != "inventory"
            or envelope.producer_domain != "inventory"
            or envelope.aggregate_type != "inventory_adjustment"
            or envelope.aggregate_version is None
            or envelope.company_id is None
        ):
            raise ValueError("Unsupported inventory movement event envelope.")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            payload = message.payload
            postings = payload.get("postings")
            if not isinstance(postings, list) or not postings:
                raise ValueError("Inventory movement event must include postings.")
            reason = payload.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Inventory movement event must include a reason.")
            session.add(
                InventoryMovementProjectionModel(
                    event_id=message.message_id,
                    message_type=message.message_type,
                    aggregate_type=message.aggregate_type,
                    transaction_id=message.aggregate_id,
                    aggregate_version=message.aggregate_version or 1,
                    company_id=message.company_id,
                    reason=reason.strip(),
                    posting_count=len(postings),
                    payload=payload,
                )
            )
            await session.flush()

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=INVENTORY_MOVEMENT_PROJECTOR,
                envelope=envelope,
                effect=effect,
            )


__all__ = [
    "INVENTORY_ADJUSTED",
    "INVENTORY_MOVEMENT_PROJECTOR",
    "SUPPORTED_EVENTS",
    "InventoryMovementProjectionConsumer",
    "InventoryMovementProjectionModel",
]

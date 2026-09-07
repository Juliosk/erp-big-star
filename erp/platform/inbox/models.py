"""SQLAlchemy mapping for idempotent message consumption."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class InboxStatus(StrEnum):
    """Durable processing states for one consumer/message pair."""

    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class InboxEventModel(Base):
    """A consumer's durable receipt of one globally identified event."""

    __tablename__ = "inbox_event"
    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_inbox_event_consumer_event"),
        Index("ix_inbox_event_status_received", "status", "received_at"),
        {"schema": "platform"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    consumer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=InboxStatus.PROCESSING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["InboxEventModel", "InboxStatus"]

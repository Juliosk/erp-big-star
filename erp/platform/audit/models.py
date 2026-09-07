"""SQLAlchemy mapping for immutable business audit events."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class AuditEventModel(Base):
    """Append-only record of a relevant state transition."""

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_entity", "module", "entity_type", "entity_id"),
        Index("ix_audit_event_correlation_id", "correlation_id"),
        {"schema": "platform"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    company_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    before_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


__all__ = ["AuditEventModel"]

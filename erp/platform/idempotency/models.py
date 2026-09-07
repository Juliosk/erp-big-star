"""SQLAlchemy mapping for replayable command results."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class IdempotencyStatus(StrEnum):
    """Lifecycle of a protected command execution."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"


class IdempotencyRecordModel(Base):
    """Scoped key, request fingerprint and reusable public response."""

    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint(
            "scope", "operation", "idempotency_key", name="uq_idempotency_scope_operation_key"
        ),
        Index("ix_idempotency_record_expires_at", "expires_at"),
        {"schema": "platform"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(150), nullable=False)
    operation: Mapped[str] = mapped_column(String(150), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IdempotencyStatus.PROCESSING
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["IdempotencyRecordModel", "IdempotencyStatus"]

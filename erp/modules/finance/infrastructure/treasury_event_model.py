"""Tenant-bound persistence for asynchronous Treasury source state."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class TreasurySourceCursorModel(Base):
    """Latest accepted version/timestamp for one upstream tenant aggregate."""

    __tablename__ = "treasury_source_cursor"
    __table_args__ = (
        CheckConstraint("aggregate_version >= 1", name="version"),
        CheckConstraint(
            "producer_module IN ('finance', 'procurement', 'fiscal', 'workflow')",
            name="producer_module",
        ),
        Index(
            "ix_treasury_source_cursor_company_source",
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
        ),
        {"schema": "finance"},
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), primary_key=True
    )
    producer_module: Mapped[str] = mapped_column(String(32), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    aggregate_id: Mapped[UUID] = mapped_column(primary_key=True)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[UUID] = mapped_column(nullable=False)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    event_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaymentBatchReviewModel(Base):
    """Merged reassessment state for a payment batch with immutable items."""

    __tablename__ = "payment_batch_review"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "payment_batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_payment_batch_review_company_batch",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "payment_batch_id",
            name="uq_payment_batch_review_company_batch",
        ),
        CheckConstraint(
            "status IN ('BLOCKED', 'REVIEW_REQUIRED', 'CLEARED')",
            name="status",
        ),
        CheckConstraint("revision >= 1", name="revision"),
        Index(
            "ix_payment_batch_review_company_status",
            "company_id",
            "status",
            "last_event_at",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    payment_batch_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_states: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = ["PaymentBatchReviewModel", "TreasurySourceCursorModel"]

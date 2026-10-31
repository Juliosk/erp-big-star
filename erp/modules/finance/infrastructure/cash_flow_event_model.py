"""Durable cursor and work queue for event-driven Cash Flow recomposition."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class CashFlowSourceCursorModel(Base):
    """Latest accepted upstream fact for one tenant aggregate."""

    __tablename__ = "cash_flow_source_cursor"
    __table_args__ = (
        CheckConstraint("aggregate_version >= 1", name="version"),
        Index(
            "ix_cash_flow_source_cursor_company_event",
            "company_id",
            "event_occurred_at",
            "event_id",
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CashFlowRecompositionRequestModel(Base):
    """Coalesced durable work item for the latest projection of one tenant."""

    __tablename__ = "cash_flow_recomposition_request"
    __table_args__ = (
        CheckConstraint("source_aggregate_version >= 1", name="source_version"),
        CheckConstraint("revision >= 1", name="revision"),
        Index(
            "ix_cash_flow_recomposition_request_claim",
            "company_id",
            "requested_at",
            "projection_id",
        ),
        {"schema": "finance"},
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), primary_key=True
    )
    projection_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_event_id: Mapped[UUID] = mapped_column(nullable=False)
    source_event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    source_producer_module: Mapped[str] = mapped_column(String(32), nullable=False)
    source_aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    source_aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


__all__ = ["CashFlowRecompositionRequestModel", "CashFlowSourceCursorModel"]

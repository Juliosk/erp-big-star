"""Durable monotonic state for event-driven bank reconciliation."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class BankReconciliationSourceCursorModel(Base):
    """Latest accepted upstream fact for one tenant aggregate."""

    __tablename__ = "bank_reconciliation_source_cursor"
    __table_args__ = (
        CheckConstraint("aggregate_version >= 1", name="version"),
        Index(
            "ix_bank_reconciliation_source_cursor_company_event",
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
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BankReconciliationCandidateModel(Base):
    """Tenant-owned candidate projection populated exclusively from accepted events."""

    __tablename__ = "bank_reconciliation_candidate"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_bank_reconciliation_candidate_company_id"),
        CheckConstraint(
            "source IN ('RECEIVABLE_M13', 'TREASURY_M12')",
            name="source",
        ),
        CheckConstraint("direction IN ('CREDIT', 'DEBIT')", name="direction"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("source_version >= 1", name="version"),
        Index(
            "ix_bank_reconciliation_candidate_lookup",
            "company_id",
            "active",
            "direction",
            "expected_on",
            "amount",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "BankReconciliationCandidateModel",
    "BankReconciliationSourceCursorModel",
]

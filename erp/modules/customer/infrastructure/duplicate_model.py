"""SQLAlchemy mappings for duplicate candidates and merge requests."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class CustomerDuplicateCandidateModel(Base):
    __tablename__ = "customer_duplicate_candidate"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "source_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_duplicate_source",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "candidate_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_duplicate_candidate",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "source_customer_id",
            "candidate_customer_id",
            name="uq_customer_duplicate_candidate_pair",
        ),
        CheckConstraint("source_customer_id <> candidate_customer_id", name="different_customers"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence"),
        CheckConstraint("status IN ('SUGGESTED', 'MERGE_REQUESTED')", name="status"),
        Index("ix_customer_duplicate_source", "company_id", "source_customer_id", "confidence"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    source_customer_id: Mapped[UUID] = mapped_column(nullable=False)
    candidate_customer_id: Mapped[UUID] = mapped_column(nullable=False)
    confidence: Mapped[int] = mapped_column(nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class CustomerMergeRequestModel(OptimisticLockMixin, Base):
    __tablename__ = "customer_merge"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "source_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_merge_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "candidate_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_merge_candidate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "surviving_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_merge_survivor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id",
            "source_customer_id",
            "candidate_customer_id",
            "status",
            name="uq_customer_merge_pending_pair",
        ),
        CheckConstraint("source_customer_id <> candidate_customer_id", name="different_customers"),
        CheckConstraint(
            "surviving_customer_id IN (source_customer_id, candidate_customer_id)",
            name="survivor_in_pair",
        ),
        CheckConstraint("status IN ('PENDING_APPROVAL')", name="status"),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500 AND reason = btrim(reason)",
            name="reason",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_customer_merge_source", "company_id", "source_customer_id", "id"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    source_customer_id: Mapped[UUID] = mapped_column(nullable=False)
    candidate_customer_id: Mapped[UUID] = mapped_column(nullable=False)
    surviving_customer_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["CustomerDuplicateCandidateModel", "CustomerMergeRequestModel"]

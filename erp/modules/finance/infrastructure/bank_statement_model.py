"""Tenant-bound SQLAlchemy mappings for M12 bank reconciliation."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class BankStatementModel(OptimisticLockMixin, Base):
    __tablename__ = "bank_statement"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_bank_statement_company_id"),
        UniqueConstraint(
            "company_id",
            "bank_account_id",
            "source_hash",
            name="uq_bank_statement_company_account_hash",
        ),
        CheckConstraint("period_start <= period_end", name="period"),
        CheckConstraint("source IN ('OFX', 'CSV')", name="source"),
        CheckConstraint("source_hash ~ '^[0-9a-f]{64}$'", name="source_hash"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_bank_statement_company_account_period",
            "company_id",
            "bank_account_id",
            "period_start",
            "period_end",
            "id",
        ),
        Index("ix_bank_statement_company_hash", "company_id", "source_hash"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    bank_account_id: Mapped[UUID] = mapped_column(nullable=False)
    bank_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class BankMovementModel(Base):
    __tablename__ = "bank_movement"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "bank_statement_id"],
            ["finance.bank_statement.company_id", "finance.bank_statement.id"],
            name="fk_bank_movement_company_statement",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "bank_statement_id",
            "id",
            name="uq_bank_movement_company_statement_id",
        ),
        UniqueConstraint(
            "company_id",
            "bank_statement_id",
            "external_id",
            name="uq_bank_movement_statement_external_id",
        ),
        UniqueConstraint(
            "company_id",
            "bank_statement_id",
            "sequence_number",
            name="uq_bank_movement_statement_sequence",
        ),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("sequence_number >= 1", name="sequence"),
        CheckConstraint("direction IN ('CREDIT', 'DEBIT')", name="direction"),
        CheckConstraint(
            "kind IN ('TRANSFER', 'PAYMENT', 'RECEIPT', 'BANK_FEE', "
            "'INTEREST', 'TAX', 'OTHER')",
            name="kind",
        ),
        CheckConstraint("status IN ('PENDING', 'RECONCILED')", name="status"),
        CheckConstraint(
            "(status = 'PENDING' AND matched_reference_id IS NULL AND "
            "reconciled_at IS NULL AND match_score IS NULL) OR "
            "(status = 'RECONCILED' AND matched_reference_id IS NOT NULL AND "
            "reconciled_at IS NOT NULL AND match_score BETWEEN 0 AND 1)",
            name="reconciliation_evidence",
        ),
        Index(
            "ix_bank_movement_company_account_date",
            "company_id",
            "bank_account_id",
            "booked_on",
            "status",
            "id",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    bank_statement_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    bank_account_id: Mapped[UUID] = mapped_column(nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    matched_reference_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class StatementImportAuditModel(Base):
    __tablename__ = "statement_import_audit"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "bank_statement_id"],
            ["finance.bank_statement.company_id", "finance.bank_statement.id"],
            name="fk_statement_import_company_statement",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "bank_statement_id",
            name="uq_statement_import_company_statement",
        ),
        CheckConstraint("source IN ('OFX', 'CSV')", name="source"),
        CheckConstraint("source_hash ~ '^[0-9a-f]{64}$'", name="hash"),
        CheckConstraint("file_size_bytes >= 0", name="size"),
        CheckConstraint("movement_count > 0", name="count"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    bank_statement_id: Mapped[UUID] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    movement_count: Mapped[int] = mapped_column(nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ConciliationRecordModel(Base):
    __tablename__ = "conciliation_record"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "bank_statement_id", "bank_movement_id"],
            [
                "finance.bank_movement.company_id",
                "finance.bank_movement.bank_statement_id",
                "finance.bank_movement.id",
            ],
            name="fk_conciliation_record_company_movement",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "bank_movement_id",
            name="uq_conciliation_record_company_movement",
        ),
        CheckConstraint("match_score BETWEEN 0 AND 1", name="score"),
        Index(
            "ix_conciliation_record_company_reference",
            "company_id",
            "matched_reference_id",
            "reconciled_at",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    bank_statement_id: Mapped[UUID] = mapped_column(nullable=False)
    bank_movement_id: Mapped[UUID] = mapped_column(nullable=False)
    matched_reference_id: Mapped[UUID] = mapped_column(nullable=False)
    match_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


__all__ = [
    "BankMovementModel",
    "BankStatementModel",
    "ConciliationRecordModel",
    "StatementImportAuditModel",
]

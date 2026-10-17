"""Tenant-bound SQLAlchemy mappings for M12 payables and provisions."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class ProvisionalEntryModel(OptimisticLockMixin, Base):
    __tablename__ = "provisional_entry"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_provisional_entry_company_id"),
        UniqueConstraint(
            "company_id",
            "origin",
            "source_id",
            "source_version",
            name="uq_provisional_entry_source",
        ),
        CheckConstraint(
            "origin IN ('AUTHORIZED_FISCAL_DOCUMENT', 'APPROVED_PURCHASE_ORDER')",
            name="origin",
        ),
        CheckConstraint("status IN ('OPEN', 'CONVERTED', 'VOIDED')", name="status"),
        CheckConstraint("source_version >= 1", name="source_version"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_provisional_entry_company_status", "company_id", "status", "id"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    source_version: Mapped[int] = mapped_column(nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payable_id: Mapped[UUID | None] = mapped_column(nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PayableModel(OptimisticLockMixin, Base):
    __tablename__ = "payable"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "provisional_entry_id"],
            ["finance.provisional_entry.company_id", "finance.provisional_entry.id"],
            name="fk_payable_company_provisional_entry",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_payable_company_id"),
        UniqueConstraint(
            "company_id",
            "document_number",
            "supplier_id",
            name="uq_payable_company_document_supplier",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'SCHEDULED', 'PAID')",
            name="status",
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "nominal_amount > 0 AND interest_amount >= 0 AND discount_amount >= 0 "
            "AND surcharge_amount >= 0",
            name="amounts",
        ),
        Index("ix_payable_company_status", "company_id", "status", "id"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    document_number: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    provisional_entry_id: Mapped[UUID | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    nominal_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    interest_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    surcharge_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    decision_by: Mapped[UUID | None] = mapped_column(nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PayableInstallmentModel(Base):
    __tablename__ = "payable_installment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "payable_id"],
            ["finance.payable.company_id", "finance.payable.id"],
            name="fk_payable_installment_company_payable",
            ondelete="CASCADE",
        ),
        UniqueConstraint("company_id", "id", name="uq_payable_installment_company_id"),
        UniqueConstraint(
            "company_id",
            "payable_id",
            "id",
            name="uq_payable_installment_company_payable_id",
        ),
        UniqueConstraint(
            "company_id",
            "payable_id",
            "installment_number",
            name="uq_payable_installment_number",
        ),
        CheckConstraint("installment_number >= 1", name="number"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("status IN ('OPEN', 'SCHEDULED', 'PAID')", name="status"),
        Index(
            "ix_payable_installment_company_payable",
            "company_id",
            "payable_id",
            "installment_number",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    payable_id: Mapped[UUID] = mapped_column(nullable=False)
    installment_number: Mapped[int] = mapped_column(nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule_id: Mapped[UUID | None] = mapped_column(nullable=True)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["PayableInstallmentModel", "PayableModel", "ProvisionalEntryModel"]

"""Tenant-bound SQLAlchemy mappings for M12 payment execution."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_STATUS_CHECK = (
    "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'RELEASED', "
    "'SUBMITTED', 'CONFIRMED', 'REJECTED', 'CANCELLED')"
)


class PaymentBatchModel(OptimisticLockMixin, Base):
    __tablename__ = "payment_batch"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_payment_batch_company_id"),
        UniqueConstraint("company_id", "code", name="uq_payment_batch_company_code"),
        CheckConstraint(_STATUS_CHECK, name="status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint("total_amount > 0", name="total_amount"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "remittance_format IN ('CNAB_240', 'CNAB_400', 'PIX_API')",
            name="remittance_format",
        ),
        CheckConstraint(
            "execution_mode IN ('DRY_RUN', 'HOMOLOGATION', 'PRODUCTION')",
            name="execution_mode",
        ),
        CheckConstraint(
            "status NOT IN ('APPROVED', 'RELEASED', 'SUBMITTED', 'CONFIRMED') "
            "OR approved_by IS NOT NULL",
            name="approval_evidence",
        ),
        CheckConstraint(
            "status NOT IN ('RELEASED', 'SUBMITTED', 'CONFIRMED') OR released_by IS NOT NULL",
            name="release_evidence",
        ),
        CheckConstraint(
            "status NOT IN ('SUBMITTED', 'CONFIRMED') OR "
            "(submission_protocol IS NOT NULL AND submitted_at IS NOT NULL)",
            name="submission_evidence",
        ),
        CheckConstraint(
            "(status = 'CONFIRMED' AND bank_confirmation_protocol IS NOT NULL "
            "AND bank_confirmation_status IS NOT NULL AND bank_confirmed_at IS NOT NULL "
            "AND bank_confirmed_amount = total_amount) OR "
            "(status <> 'CONFIRMED' AND bank_confirmation_protocol IS NULL "
            "AND bank_confirmation_status IS NULL AND bank_confirmed_at IS NULL "
            "AND bank_confirmed_amount IS NULL)",
            name="bank_confirmation",
        ),
        Index(
            "ix_payment_batch_company_status",
            "company_id",
            "status",
            "scheduled_date",
            "id",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    treasury_account_id: Mapped[UUID] = mapped_column(nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    remittance_format: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(nullable=True)
    released_by: Mapped[UUID | None] = mapped_column(nullable=True)
    submission_protocol: Mapped[str | None] = mapped_column(String(120), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transition_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bank_confirmation_protocol: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_confirmation_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bank_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bank_confirmed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PaymentBatchItemModel(Base):
    __tablename__ = "payment_batch_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "payment_batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_payment_batch_item_company_batch",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "payable_id", "installment_id"],
            [
                "finance.payable_installment.company_id",
                "finance.payable_installment.payable_id",
                "finance.payable_installment.id",
            ],
            name="fk_payment_batch_item_company_installment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_payment_batch_item_company_matching",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_payment_batch_item_company_supplier",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_payment_batch_item_company_id"),
        UniqueConstraint(
            "company_id",
            "payment_batch_id",
            "installment_id",
            name="uq_payment_batch_item_batch_installment",
        ),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint(
            "beneficiary_account_type IN ('CHECKING', 'SAVINGS', 'PAYMENT')",
            name="account_type",
        ),
        Index(
            "ix_payment_batch_item_company_batch",
            "company_id",
            "payment_batch_id",
            "due_date",
            "id",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    payment_batch_id: Mapped[UUID] = mapped_column(nullable=False)
    payable_id: Mapped[UUID] = mapped_column(nullable=False)
    installment_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    matching_session_id: Mapped[UUID] = mapped_column(nullable=False)
    payable_created_by: Mapped[UUID] = mapped_column(nullable=False)
    payable_approved_by: Mapped[UUID] = mapped_column(nullable=False)
    beneficiary_bank_code: Mapped[str] = mapped_column(String(3), nullable=False)
    beneficiary_branch_number: Mapped[str] = mapped_column(String(5), nullable=False)
    beneficiary_account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    beneficiary_account_digit: Mapped[str] = mapped_column(String(2), nullable=False)
    beneficiary_account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    beneficiary_holder_name: Mapped[str] = mapped_column(String(120), nullable=False)
    beneficiary_holder_tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class BatchAuditLogModel(Base):
    __tablename__ = "batch_audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "payment_batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_batch_audit_company_batch",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "payment_batch_id",
            "aggregate_version",
            name="uq_batch_audit_batch_version",
        ),
        CheckConstraint("aggregate_version >= 1", name="version"),
        CheckConstraint(_STATUS_CHECK.replace("status", "to_status"), name="to_status"),
        CheckConstraint(
            "from_status IS NULL OR " + _STATUS_CHECK.replace("status", "from_status"),
            name="from_status",
        ),
        Index(
            "ix_batch_audit_company_batch",
            "company_id",
            "payment_batch_id",
            "aggregate_version",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    payment_batch_id: Mapped[UUID] = mapped_column(nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


__all__ = ["BatchAuditLogModel", "PaymentBatchItemModel", "PaymentBatchModel"]

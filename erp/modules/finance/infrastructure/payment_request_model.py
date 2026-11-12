"""Tenant-bound SQLAlchemy mappings for M12 payment requests."""

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


class PaymentRequestModel(OptimisticLockMixin, Base):
    __tablename__ = "payment_request"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_payment_request_batch",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', "
            "'CANCELLED', 'BATCHED')",
            name="ck_payment_request_status",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payment_request_currency"),
        CheckConstraint("total_amount > 0", name="ck_payment_request_total"),
        CheckConstraint("version >= 1", name="ck_payment_request_version"),
        CheckConstraint(
            "status NOT IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', "
            "'BATCHED') OR workflow_instance_id IS NOT NULL",
            name="ck_payment_request_workflow",
        ),
        CheckConstraint(
            "status NOT IN ('APPROVED', 'REJECTED', 'BATCHED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_payment_request_decision",
        ),
        CheckConstraint(
            "(status = 'BATCHED') = (batch_id IS NOT NULL)",
            name="ck_payment_request_batch",
        ),
        CheckConstraint(
            "status NOT IN ('REJECTED', 'CANCELLED') OR transition_reason IS NOT NULL",
            name="ck_payment_request_reason",
        ),
        UniqueConstraint("company_id", "id", name="uq_payment_request_company_id"),
        UniqueConstraint("company_id", "code", name="uq_payment_request_code"),
        Index(
            "ix_payment_request_queue",
            "company_id",
            "status",
            "scheduled_on",
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
    requested_by: Mapped[UUID] = mapped_column(nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_on: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    workflow_instance_id: Mapped[UUID | None] = mapped_column(nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_id: Mapped[UUID | None] = mapped_column(nullable=True)
    transition_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PaymentRequestItemModel(Base):
    __tablename__ = "payment_request_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "payment_request_id"],
            ["finance.payment_request.company_id", "finance.payment_request.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "payable_id", "installment_id"],
            [
                "finance.payable_installment.company_id",
                "finance.payable_installment.payable_id",
                "finance.payable_installment.id",
            ],
            name="fk_payment_request_item_installment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            [
                "procurement.matching_session.company_id",
                "procurement.matching_session.id",
            ],
            name="fk_payment_request_item_matching",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_payment_request_item_supplier",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="ck_payment_request_item_amount"),
        CheckConstraint("item_sequence >= 1", name="ck_payment_request_item_sequence"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payment_request_item_currency"),
        CheckConstraint(
            "beneficiary_account_type IN ('CHECKING', 'SAVINGS', 'PAYMENT')",
            name="ck_payment_request_item_account_type",
        ),
        UniqueConstraint("company_id", "id", name="uq_payment_request_item_scope"),
        UniqueConstraint(
            "company_id",
            "payment_request_id",
            "installment_id",
            name="uq_payment_request_item_installment",
        ),
        UniqueConstraint(
            "company_id",
            "payment_request_id",
            "item_sequence",
            name="uq_payment_request_item_sequence",
        ),
        Index(
            "ix_payment_request_item_request",
            "company_id",
            "payment_request_id",
            "due_date",
            "id",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    payment_request_id: Mapped[UUID] = mapped_column(nullable=False)
    item_sequence: Mapped[int] = mapped_column(nullable=False)
    payable_id: Mapped[UUID] = mapped_column(nullable=False)
    installment_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    matching_session_id: Mapped[UUID] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    beneficiary_bank_code: Mapped[str] = mapped_column(String(3), nullable=False)
    beneficiary_branch_number: Mapped[str] = mapped_column(String(5), nullable=False)
    beneficiary_account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    beneficiary_account_digit: Mapped[str] = mapped_column(String(2), nullable=False)
    beneficiary_account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    beneficiary_holder_name: Mapped[str] = mapped_column(String(120), nullable=False)
    beneficiary_holder_tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["PaymentRequestItemModel", "PaymentRequestModel"]

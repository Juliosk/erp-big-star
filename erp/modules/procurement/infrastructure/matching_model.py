"""Tenant-bound SQLAlchemy mappings for M6 three-way matching."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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


class MatchingSessionModel(OptimisticLockMixin, Base):
    __tablename__ = "matching_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_matching_session_company_supplier",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["procurement.purchase_order.company_id", "procurement.purchase_order.id"],
            name="fk_matching_session_company_purchase_order",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "provisional_entry_id"],
            ["finance.provisional_entry.company_id", "finance.provisional_entry.id"],
            name="fk_matching_session_company_provisional_entry",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "payable_id"],
            ["finance.payable.company_id", "finance.payable.id"],
            name="fk_matching_session_company_payable",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_matching_session_company_id"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'MATCHED', 'DISCREPANCY_DETECTED', "
            "'OVERRIDDEN', 'REJECTED')",
            name="status",
        ),
        CheckConstraint(
            "report_status IS NULL OR report_status IN "
            "('MATCHED', 'TOLERANCE_EXCEEDED', 'QUANTITY_MISMATCH', 'PRICE_MISMATCH')",
            name="report_status",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint(
            "purchase_order_version >= 1 AND provisional_entry_version >= 1 "
            "AND tolerance_policy_version >= 1 AND version >= 1",
            name="versions",
        ),
        CheckConstraint(
            "(payable_id IS NULL AND payable_version IS NULL) OR "
            "(payable_id IS NOT NULL AND payable_version >= 1)",
            name="payable_reference",
        ),
        CheckConstraint(
            "purchase_order_total_amount > 0 AND invoiced_total_amount > 0 "
            "AND obligation_amount > 0",
            name="amounts",
        ),
        CheckConstraint(
            "unit_price_variance_percentage BETWEEN 0 AND 100 "
            "AND quantity_variance_percentage BETWEEN 0 AND 100 "
            "AND rounding_absolute_limit BETWEEN 0 AND 1",
            name="tolerances",
        ),
        Index("ix_matching_session_company_status", "company_id", "status", "id"),
        Index(
            "ix_matching_session_company_purchase_order",
            "company_id",
            "purchase_order_id",
            "id",
        ),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(nullable=False)
    purchase_order_version: Mapped[int] = mapped_column(nullable=False)
    purchase_order_total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    purchase_order_captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    goods_receipts_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    fiscal_documents_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    invoiced_total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    receiving_fiscal_captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provisional_entry_id: Mapped[UUID] = mapped_column(nullable=False)
    provisional_entry_version: Mapped[int] = mapped_column(nullable=False)
    payable_id: Mapped[UUID | None] = mapped_column(nullable=True)
    payable_version: Mapped[int | None] = mapped_column(nullable=True)
    obligation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    financial_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unit_price_variance_percentage: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    quantity_variance_percentage: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    rounding_absolute_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tolerance_policy_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    report_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_by: Mapped[UUID | None] = mapped_column(nullable=True)
    decision_workflow_instance_id: Mapped[UUID | None] = mapped_column(nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class MatchingSessionItemModel(Base):
    __tablename__ = "matching_session_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_matching_item_company_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "purchase_order_item_id"],
            ["procurement.purchase_order_item.company_id", "procurement.purchase_order_item.id"],
            name="fk_matching_item_company_purchase_order_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "goods_receipt_item_id"],
            ["procurement.receipt_item.company_id", "procurement.receipt_item.id"],
            name="fk_matching_item_company_goods_receipt_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "fiscal_document_item_id"],
            [
                "fiscal.inbound_fiscal_document_item.company_id",
                "fiscal.inbound_fiscal_document_item.id",
            ],
            name="fk_matching_item_company_fiscal_document_item",
            ondelete="RESTRICT",
        ),
        CheckConstraint("match_key ~ '^[A-Z0-9][A-Z0-9._/-]*$'", name="key"),
        CheckConstraint("line_number >= 1", name="line_number"),
        CheckConstraint(
            "ordered_quantity > 0 AND received_quantity >= 0 AND invoiced_quantity > 0",
            name="quantities",
        ),
        CheckConstraint("ordered_unit_price >= 0 AND invoiced_unit_price >= 0", name="prices"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint(
            "result_status IS NULL OR result_status IN "
            "('MATCHED', 'TOLERANCE_EXCEEDED', 'QUANTITY_MISMATCH', 'PRICE_MISMATCH')",
            name="result_status",
        ),
        Index(
            "ix_matching_item_company_session",
            "company_id",
            "matching_session_id",
            "line_number",
        ),
        UniqueConstraint(
            "company_id",
            "matching_session_id",
            "line_number",
            name="uq_matching_item_session_line_number",
        ),
        {"schema": "procurement"},
    )

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    matching_session_id: Mapped[UUID] = mapped_column(primary_key=True)
    line_number: Mapped[int] = mapped_column(nullable=False)
    match_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    purchase_order_item_id: Mapped[UUID] = mapped_column(nullable=False)
    goods_receipt_item_id: Mapped[UUID] = mapped_column(nullable=False)
    fiscal_document_item_id: Mapped[UUID] = mapped_column(nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    invoiced_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    ordered_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    invoiced_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    result_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    unit_price_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    allowed_quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    allowed_unit_price_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    reasons: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)


class MatchingAuditLogModel(Base):
    __tablename__ = "matching_audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_matching_audit_company_session",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "matching_session_id",
            "aggregate_version",
            name="uq_matching_audit_session_version",
        ),
        CheckConstraint("aggregate_version >= 1", name="version"),
        CheckConstraint(
            "to_status IN ('PENDING', 'RUNNING', 'MATCHED', 'DISCREPANCY_DETECTED', "
            "'OVERRIDDEN', 'REJECTED')",
            name="to_status",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('PENDING', 'RUNNING', 'MATCHED', 'DISCREPANCY_DETECTED', 'OVERRIDDEN', 'REJECTED')",
            name="from_status",
        ),
        Index(
            "ix_matching_audit_company_session",
            "company_id",
            "matching_session_id",
            "aggregate_version",
        ),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    matching_session_id: Mapped[UUID] = mapped_column(nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


__all__ = ["MatchingAuditLogModel", "MatchingSessionItemModel", "MatchingSessionModel"]

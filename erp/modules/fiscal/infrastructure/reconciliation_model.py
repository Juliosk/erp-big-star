"""Tenant-bound persistence model for physical-fiscal reconciliation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class FiscalReceivingReconciliationModel(OptimisticLockMixin, Base):
    __tablename__ = "receiving_reconciliation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "inbound_fiscal_document_id"],
            [
                "fiscal.inbound_fiscal_document.company_id",
                "fiscal.inbound_fiscal_document.id",
            ],
            name="fk_reconciliation_company_inbound",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "goods_receipt_id"],
            ["procurement.goods_receipt.company_id", "procurement.goods_receipt.id"],
            name="fk_reconciliation_company_receipt",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_receiving_reconciliation_company_id"),
        UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            name="uq_reconciliation_inbound",
        ),
        UniqueConstraint("company_id", "goods_receipt_id", name="uq_reconciliation_receipt"),
        CheckConstraint("status IN ('DIVERGENT', 'POSTED')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_reconciliation_company_status",
            "company_id",
            "status",
            "reconciled_at",
        ),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    inbound_fiscal_document_id: Mapped[UUID] = mapped_column(nullable=False)
    goods_receipt_id: Mapped[UUID] = mapped_column(nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    report: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    financial_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    physical_pending: Mapped[bool] = mapped_column(Boolean, nullable=False)
    inventory_transaction_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["FiscalReceivingReconciliationModel"]

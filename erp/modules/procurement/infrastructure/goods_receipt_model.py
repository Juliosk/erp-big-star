"""Tenant-bound SQLAlchemy mappings for M6 physical goods receipts."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class GoodsReceiptModel(OptimisticLockMixin, Base):
    __tablename__ = "goods_receipt"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["procurement.purchase_order.company_id", "procurement.purchase_order.id"],
            name="fk_goods_receipt_company_purchase_order",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_goods_receipt_company_id"),
        UniqueConstraint("company_id", "number", name="uq_goods_receipt_company_number"),
        CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="number_format"),
        CheckConstraint(
            "status IN ('DRAFT', 'RECEIVED', 'INSPECTED', 'POSTED', 'REJECTED')",
            name="status",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_goods_receipt_company_status", "company_id", "status", "id"),
        Index("ix_goods_receipt_company_order", "company_id", "purchase_order_id", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    received_by: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    physically_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class ReceiptItemModel(Base):
    __tablename__ = "receipt_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "goods_receipt_id"],
            ["procurement.goods_receipt.company_id", "procurement.goods_receipt.id"],
            name="fk_receipt_item_company_receipt",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "purchase_order_item_id"],
            ["procurement.purchase_order_item.company_id", "procurement.purchase_order_item.id"],
            name="fk_receipt_item_company_order_item",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_receipt_item_company_id"),
        UniqueConstraint(
            "company_id",
            "goods_receipt_id",
            "purchase_order_item_id",
            name="uq_receipt_item_order_item",
        ),
        UniqueConstraint(
            "company_id", "goods_receipt_id", "line_number", name="uq_receipt_item_line_number"
        ),
        CheckConstraint("line_number >= 1", name="line_number_positive"),
        CheckConstraint("ordered_quantity > 0", name="ordered_quantity_positive"),
        CheckConstraint(
            "previously_received_quantity >= 0", name="previously_received_non_negative"
        ),
        CheckConstraint("expected_quantity > 0", name="expected_quantity_positive"),
        CheckConstraint("received_quantity > 0", name="received_quantity_positive"),
        CheckConstraint(
            "tolerance_percentage >= 0 AND tolerance_percentage <= 100",
            name="tolerance_range",
        ),
        CheckConstraint("approved_quantity >= 0", name="approved_quantity_non_negative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_quantity_non_negative"),
        CheckConstraint("quarantine_quantity >= 0", name="quarantine_quantity_non_negative"),
        CheckConstraint(
            "inspection_disposition IS NULL OR inspection_disposition IN "
            "('APPROVE', 'PARTIAL_ACCEPTANCE', 'REJECT', 'QUARANTINE')",
            name="inspection_disposition",
        ),
        Index("ix_receipt_item_receipt", "company_id", "goods_receipt_id", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    goods_receipt_id: Mapped[UUID] = mapped_column(nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    purchase_order_item_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    previously_received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tolerance_percentage: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    specification_conforms: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discrepancy_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    lot_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inspection_id: Mapped[UUID | None] = mapped_column(nullable=True)
    inspection_disposition: Mapped[str | None] = mapped_column(String(24), nullable=True)
    approved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("0.000000"), server_default=text("0")
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("0.000000"), server_default=text("0")
    )
    quarantine_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("0.000000"), server_default=text("0")
    )
    inspection_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available_posting_request_id: Mapped[UUID | None] = mapped_column(nullable=True)
    quarantine_posting_request_id: Mapped[UUID | None] = mapped_column(nullable=True)
    available_inventory_transaction_id: Mapped[UUID | None] = mapped_column(nullable=True)
    quarantine_inventory_transaction_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["GoodsReceiptModel", "ReceiptItemModel"]

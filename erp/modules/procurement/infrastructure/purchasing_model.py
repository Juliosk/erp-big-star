"""M6-owned SQLAlchemy mappings for requisitions and purchase orders."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class PurchaseRequisitionModel(OptimisticLockMixin, Base):
    __tablename__ = "purchase_requisition"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_purchase_requisition_company_id"),
        UniqueConstraint("company_id", "number", name="uq_purchase_requisition_company_number"),
        CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="number_format"),
        CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_purchase_requisition_company_status", "company_id", "status", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(nullable=False)
    cost_center_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    justification: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class RequisitionItemModel(Base):
    __tablename__ = "requisition_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "requisition_id"],
            ["procurement.purchase_requisition.company_id", "procurement.purchase_requisition.id"],
            name="fk_requisition_item_company_requisition",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_requisition_item_company_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_requisition_item_company_id"),
        UniqueConstraint(
            "company_id", "requisition_id", "product_id", name="uq_requisition_item_product"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_of_measure ~ '^[A-Z0-9][A-Z0-9._-]{0,15}$'", name="uom_format"),
        CheckConstraint("urgency IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')", name="urgency"),
        Index("ix_requisition_item_requisition", "company_id", "requisition_id", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    requisition_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(16), nullable=False)
    needed_by: Mapped[date] = mapped_column(Date, nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    specification: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class PurchaseOrderModel(OptimisticLockMixin, Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_purchase_order_company_supplier",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_requisition_id"],
            ["procurement.purchase_requisition.company_id", "procurement.purchase_requisition.id"],
            name="fk_purchase_order_company_requisition",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_purchase_order_company_id"),
        UniqueConstraint("company_id", "number", name="uq_purchase_order_company_number"),
        CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="number_format"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', "
            "'PARTIALLY_RECEIVED', 'COMPLETED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint("total_amount >= 0", name="total_non_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_purchase_order_company_status", "company_id", "status", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    source_requisition_id: Mapped[UUID] = mapped_column(nullable=False)
    buyer_id: Mapped[UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_terms_code: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_terms_description: Mapped[str] = mapped_column(String(200), nullable=False)
    payment_installment_days: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PurchaseOrderItemModel(Base):
    __tablename__ = "purchase_order_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["procurement.purchase_order.company_id", "procurement.purchase_order.id"],
            name="fk_purchase_order_item_company_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "requisition_item_id"],
            ["procurement.requisition_item.company_id", "procurement.requisition_item.id"],
            name="fk_purchase_order_item_company_requisition_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_purchase_order_item_company_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_purchase_order_item_company_id"),
        UniqueConstraint(
            "company_id",
            "purchase_order_id",
            "requisition_item_id",
            name="uq_purchase_order_item_requisition_item",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= quantity", name="receipt_range"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_purchase_order_item_order", "company_id", "purchase_order_id", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    purchase_order_id: Mapped[UUID] = mapped_column(nullable=False)
    requisition_item_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "PurchaseOrderItemModel",
    "PurchaseOrderModel",
    "PurchaseRequisitionModel",
    "RequisitionItemModel",
]

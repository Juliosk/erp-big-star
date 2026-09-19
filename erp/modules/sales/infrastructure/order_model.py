"""SQLAlchemy mappings for M4 Sales Orders."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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


class SalesOrderModel(OptimisticLockMixin, Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_order_company_id"),
        UniqueConstraint("company_id", "number", name="uq_sales_order_company_number"),
        UniqueConstraint("company_id", "source_quote_id", name="uq_sales_order_source_quote"),
        CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="number_format"),
        CheckConstraint("currency = 'BRL'", name="currency"),
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'CANCELLED', 'COMPLETED')", name="status"
        ),
        CheckConstraint("source_quote_revision_number >= 1", name="revision_positive"),
        CheckConstraint("gross_amount >= 0", name="gross_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint("net_amount = gross_amount - discount_amount", name="net_total"),
        ForeignKeyConstraint(
            ["company_id", "source_quote_id"],
            ["sales_b2b.sales_quote.company_id", "sales_b2b.sales_quote.id"],
            name="fk_sales_order_quote",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_sales_order_customer",
            ondelete="RESTRICT",
        ),
        Index("ix_sales_order_company_status", "company_id", "status", "created_at"),
        Index("ix_sales_order_customer", "company_id", "customer_id", "created_at"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    source_quote_id: Mapped[UUID] = mapped_column(nullable=False)
    source_quote_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[UUID] = mapped_column(nullable=False)
    seller_id: Mapped[UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class SalesOrderItemModel(Base):
    __tablename__ = "sales_order_item"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_order_item_company_id"),
        UniqueConstraint(
            "company_id", "order_id", "product_id", name="uq_sales_order_item_product"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        ForeignKeyConstraint(
            ["company_id", "order_id"],
            ["sales_b2b.sales_order.company_id", "sales_b2b.sales_order.id"],
            name="fk_sales_order_item_order",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "quote_revision_item_id"],
            ["sales_b2b.quote_revision_item.company_id", "sales_b2b.quote_revision_item.id"],
            name="fk_sales_order_item_quote_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_sales_order_item_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pricing_snapshot_id"],
            ["pricing.pricing_snapshot.company_id", "pricing.pricing_snapshot.id"],
            name="fk_sales_order_item_snapshot",
            ondelete="RESTRICT",
        ),
        Index("ix_sales_order_item_parent", "company_id", "order_id"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    order_id: Mapped[UUID] = mapped_column(nullable=False)
    quote_revision_item_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    pricing_snapshot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["SalesOrderItemModel", "SalesOrderModel"]

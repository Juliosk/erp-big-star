"""SQLAlchemy mappings owned by M15 B2B Sales."""

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


class SalesQuoteModel(OptimisticLockMixin, Base):
    __tablename__ = "sales_quote"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_quote_company_id"),
        UniqueConstraint("company_id", "number", name="uq_sales_quote_company_number"),
        CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="number_format"),
        CheckConstraint("currency = 'BRL'", name="currency"),
        CheckConstraint(
            "status IN ('DRAFT', 'SENT', 'ACCEPTED', 'PARTIALLY_ACCEPTED', 'LOST', 'CONVERTED')",
            name="status",
        ),
        CheckConstraint("current_revision_number >= 0", name="revision_non_negative"),
        CheckConstraint(
            "status != 'CONVERTED' OR converted_order_id IS NOT NULL",
            name="converted_requires_order",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_sales_quote_customer",
            ondelete="RESTRICT",
        ),
        Index("ix_sales_quote_company_status", "company_id", "status", "created_at"),
        Index("ix_sales_quote_customer", "company_id", "customer_id", "created_at"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[UUID] = mapped_column(nullable=False)
    seller_id: Mapped[UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    current_revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    workflow_instance_id: Mapped[UUID | None] = mapped_column(nullable=True)
    converted_order_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class QuoteRevisionModel(Base):
    __tablename__ = "quote_revision"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_quote_revision_company_id"),
        UniqueConstraint(
            "company_id", "quote_id", "revision_number", name="uq_quote_revision_number"
        ),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        CheckConstraint("gross_amount >= 0", name="gross_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint("net_amount = gross_amount - discount_amount", name="net_total"),
        ForeignKeyConstraint(
            ["company_id", "quote_id"],
            ["sales_b2b.sales_quote.company_id", "sales_b2b.sales_quote.id"],
            name="fk_quote_revision_quote",
            ondelete="RESTRICT",
        ),
        Index("ix_quote_revision_parent", "company_id", "quote_id", "revision_number"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    quote_id: Mapped[UUID] = mapped_column(nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class QuoteRevisionItemModel(Base):
    __tablename__ = "quote_revision_item"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_quote_revision_item_company_id"),
        UniqueConstraint(
            "company_id", "revision_id", "product_id", name="uq_quote_revision_item_product"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint(
            "discount_amount <= round(quantity * unit_price, 2)",
            name="discount_not_above_gross",
        ),
        ForeignKeyConstraint(
            ["company_id", "revision_id"],
            ["sales_b2b.quote_revision.company_id", "sales_b2b.quote_revision.id"],
            name="fk_quote_revision_item_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_quote_revision_item_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pricing_snapshot_id"],
            ["pricing.pricing_snapshot.company_id", "pricing.pricing_snapshot.id"],
            name="fk_quote_revision_item_pricing_snapshot",
            ondelete="RESTRICT",
        ),
        Index("ix_quote_revision_item_parent", "company_id", "revision_id"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    revision_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    pricing_snapshot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["QuoteRevisionItemModel", "QuoteRevisionModel", "SalesQuoteModel"]

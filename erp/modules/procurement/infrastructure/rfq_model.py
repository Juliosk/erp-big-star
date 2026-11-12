"""Tenant-bound SQLAlchemy mappings for M6 requests for quotation."""

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


class RequestForQuotationModel(OptimisticLockMixin, Base):
    __tablename__ = "request_for_quotation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'CLOSED', 'AWARDED', 'CANCELLED')",
            name="ck_request_for_quotation_status",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND opened_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'OPEN' AND opened_at IS NOT NULL AND closed_at IS NULL) OR "
            "(status IN ('CLOSED', 'AWARDED') AND opened_at IS NOT NULL "
            "AND closed_at IS NOT NULL) OR status = 'CANCELLED'",
            name="ck_request_for_quotation_timeline",
        ),
        CheckConstraint(
            "(status = 'AWARDED') = (awarded_quote_id IS NOT NULL "
            "AND awarded_supplier_id IS NOT NULL AND awarded_by IS NOT NULL "
            "AND awarded_at IS NOT NULL)",
            name="ck_request_for_quotation_award",
        ),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancellation_reason IS NOT NULL)",
            name="ck_request_for_quotation_cancellation",
        ),
        CheckConstraint("version >= 1", name="ck_request_for_quotation_version"),
        UniqueConstraint("company_id", "id", name="uq_request_for_quotation_company_id"),
        UniqueConstraint("company_id", "code", name="uq_request_for_quotation_code"),
        Index(
            "ix_request_for_quotation_queue",
            "company_id",
            "status",
            "response_deadline",
            "id",
        ),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    response_deadline: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awarded_quote_id: Mapped[UUID | None] = mapped_column(nullable=True)
    awarded_supplier_id: Mapped[UUID | None] = mapped_column(nullable=True)
    awarded_by: Mapped[UUID | None] = mapped_column(nullable=True)
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class RequestForQuotationItemModel(Base):
    __tablename__ = "rfq_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "rfq_id"],
            [
                "procurement.request_for_quotation.company_id",
                "procurement.request_for_quotation.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_rfq_item_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_rfq_item_quantity"),
        CheckConstraint("item_sequence >= 1", name="ck_rfq_item_sequence"),
        UniqueConstraint("company_id", "rfq_id", "id", name="uq_rfq_item_scope"),
        UniqueConstraint(
            "company_id",
            "rfq_id",
            "product_id",
            name="uq_rfq_item_product",
        ),
        UniqueConstraint(
            "company_id",
            "rfq_id",
            "item_sequence",
            name="uq_rfq_item_sequence",
        ),
        Index("ix_rfq_item_request", "company_id", "rfq_id", "required_on", "id"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    rfq_id: Mapped[UUID] = mapped_column(nullable=False)
    item_sequence: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(8), nullable=False)
    required_on: Mapped[date] = mapped_column(Date, nullable=False)
    specification: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class RequestForQuotationSupplierModel(Base):
    __tablename__ = "rfq_supplier"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "rfq_id"],
            [
                "procurement.request_for_quotation.company_id",
                "procurement.request_for_quotation.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_rfq_supplier_supplier",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(quote_id IS NULL AND quote_sequence IS NULL AND currency IS NULL "
            "AND submitted_at IS NULL AND valid_until IS NULL "
            "AND freight_amount IS NULL) OR "
            "(quote_id IS NOT NULL AND quote_sequence >= 1 AND currency IS NOT NULL "
            "AND submitted_at IS NOT NULL AND valid_until IS NOT NULL "
            "AND freight_amount >= 0)",
            name="ck_rfq_supplier_quote_snapshot",
        ),
        CheckConstraint(
            "invitation_sequence >= 1",
            name="ck_rfq_supplier_invitation_sequence",
        ),
        UniqueConstraint("company_id", "rfq_id", "quote_id", name="uq_rfq_supplier_quote"),
        UniqueConstraint(
            "company_id",
            "rfq_id",
            "invitation_sequence",
            name="uq_rfq_supplier_invitation_sequence",
        ),
        UniqueConstraint(
            "company_id",
            "rfq_id",
            "quote_sequence",
            name="uq_rfq_supplier_quote_sequence",
        ),
        Index("ix_rfq_supplier_request", "company_id", "rfq_id", "supplier_id"),
        {"schema": "procurement"},
    )

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    rfq_id: Mapped[UUID] = mapped_column(primary_key=True)
    supplier_id: Mapped[UUID] = mapped_column(primary_key=True)
    invitation_sequence: Mapped[int] = mapped_column(nullable=False)
    quote_id: Mapped[UUID | None] = mapped_column(nullable=True)
    quote_sequence: Mapped[int | None] = mapped_column(nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    freight_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class RequestForQuotationQuoteLineModel(Base):
    __tablename__ = "rfq_supplier_quote_line"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "rfq_id", "supplier_id"],
            [
                "procurement.rfq_supplier.company_id",
                "procurement.rfq_supplier.rfq_id",
                "procurement.rfq_supplier.supplier_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "rfq_id", "rfq_item_id"],
            [
                "procurement.rfq_item.company_id",
                "procurement.rfq_item.rfq_id",
                "procurement.rfq_item.id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "offered_quantity > 0 AND unit_price > 0 AND lead_time_days >= 0",
            name="ck_rfq_quote_line_values",
        ),
        {"schema": "procurement"},
    )

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    rfq_id: Mapped[UUID] = mapped_column(primary_key=True)
    supplier_id: Mapped[UUID] = mapped_column(primary_key=True)
    rfq_item_id: Mapped[UUID] = mapped_column(primary_key=True)
    offered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    lead_time_days: Mapped[int] = mapped_column(nullable=False)


__all__ = [
    "RequestForQuotationItemModel",
    "RequestForQuotationModel",
    "RequestForQuotationQuoteLineModel",
    "RequestForQuotationSupplierModel",
]

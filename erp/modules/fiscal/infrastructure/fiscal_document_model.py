"""Tenant-bound SQLAlchemy mappings for M11 fiscal documents."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class FiscalDocumentModel(OptimisticLockMixin, Base):
    __tablename__ = "fiscal_document"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_fiscal_document_company_id"),
        UniqueConstraint(
            "company_id", "series", "number", name="uq_fiscal_document_company_series_number"
        ),
        UniqueConstraint("access_key", name="uq_fiscal_document_access_key"),
        CheckConstraint("model IN ('55', '65')", name="model"),
        CheckConstraint(
            "status IN ('DRAFT', 'ISSUING', 'AUTHORIZED', 'REJECTED', 'DENIED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint("series >= 1", name="series_positive"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "products_amount >= 0 AND freight_amount >= 0 AND discount_amount >= 0 "
            "AND tax_amount >= 0 AND total_amount >= 0",
            name="totals_non_negative",
        ),
        CheckConstraint(
            "access_key IS NULL OR access_key ~ '^[0-9]{44}$'", name="access_key_format"
        ),
        Index("ix_fiscal_document_company_status", "company_id", "status", "id"),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(2), nullable=False)
    series: Mapped[int] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    issuer_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recipient_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    products_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    access_key: Mapped[str | None] = mapped_column(String(44), nullable=True)
    authorization_protocol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorized_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_protocol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    sefaz_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class FiscalDocumentItemModel(Base):
    __tablename__ = "fiscal_document_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "fiscal_document_id"],
            ["fiscal.fiscal_document.company_id", "fiscal.fiscal_document.id"],
            name="fk_fiscal_item_company_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint("company_id", "id", name="uq_fiscal_document_item_company_id"),
        UniqueConstraint(
            "company_id",
            "fiscal_document_id",
            "line_number",
            name="uq_fiscal_document_item_line",
        ),
        CheckConstraint("line_number >= 1", name="line_positive"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint(
            "unit_price >= 0 AND freight_amount >= 0 AND discount_amount >= 0 "
            "AND total_amount >= 0",
            name="amounts",
        ),
        Index(
            "ix_fiscal_document_item_document",
            "company_id",
            "fiscal_document_id",
            "line_number",
        ),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    fiscal_document_id: Mapped[UUID] = mapped_column(nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    ncm: Mapped[str] = mapped_column(String(8), nullable=False)
    cfop: Mapped[str] = mapped_column(String(4), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["FiscalDocumentItemModel", "FiscalDocumentModel"]

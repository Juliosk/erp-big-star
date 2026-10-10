"""Tenant-bound SQLAlchemy models for inbound NF-e and MDE events."""

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class InboundFiscalDocumentModel(OptimisticLockMixin, Base):
    __tablename__ = "inbound_fiscal_document"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inbound_fiscal_document_company_id"),
        UniqueConstraint("access_key", name="uq_inbound_fiscal_document_access_key"),
        CheckConstraint("model = '55'", name="model"),
        CheckConstraint("series >= 1", name="series"),
        CheckConstraint("number >= 1", name="number"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("products_amount >= 0 AND total_amount >= 0", name="totals"),
        CheckConstraint("access_key ~ '^[0-9]{44}$'", name="access_key"),
        CheckConstraint(
            "mde_status IN ('PENDING', 'ACKNOWLEDGED', 'CONFIRMED', "
            "'UNKNOWN_OPERATION', 'OPERATION_NOT_PERFORMED')",
            name="mde_status",
        ),
        Index(
            "ix_inbound_fiscal_company_status_date",
            "company_id",
            "mde_status",
            "issued_at",
            "id",
        ),
        Index("ix_inbound_fiscal_company_supplier", "company_id", "supplier_tax_id", "id"),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    access_key: Mapped[str] = mapped_column(String(44), nullable=False)
    model: Mapped[str] = mapped_column(String(2), nullable=False)
    series: Mapped[int] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_protocol: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    supplier_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recipient_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    products_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    source_xml: Mapped[str] = mapped_column(Text, nullable=False)
    mde_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class InboundFiscalDocumentItemModel(Base):
    __tablename__ = "inbound_fiscal_document_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "inbound_fiscal_document_id"],
            [
                "fiscal.inbound_fiscal_document.company_id",
                "fiscal.inbound_fiscal_document.id",
            ],
            name="fk_inbound_item_company_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint("company_id", "id", name="uq_inbound_fiscal_document_item_company_id"),
        UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            "line_number",
            name="uq_inbound_fiscal_document_item_line",
        ),
        CheckConstraint("line_number >= 1 AND quantity > 0", name="values"),
        CheckConstraint("unit_price >= 0 AND total_amount >= 0", name="amounts"),
        Index(
            "ix_inbound_fiscal_item_document",
            "company_id",
            "inbound_fiscal_document_id",
            "line_number",
        ),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    inbound_fiscal_document_id: Mapped[UUID] = mapped_column(nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    supplier_code: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    ncm: Mapped[str] = mapped_column(String(8), nullable=False)
    cfop: Mapped[str] = mapped_column(String(4), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class MdeEventModel(Base):
    __tablename__ = "mde_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "inbound_fiscal_document_id"],
            [
                "fiscal.inbound_fiscal_document.company_id",
                "fiscal.inbound_fiscal_document.id",
            ],
            name="fk_mde_event_company_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint("company_id", "id", name="uq_mde_event_company_id"),
        UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            "sequence",
            name="uq_mde_event_document_sequence",
        ),
        UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            "event_type",
            name="uq_mde_event_document_type",
        ),
        CheckConstraint("event_type IN ('210200', '210210', '210220', '210240')", name="type"),
        CheckConstraint("sequence >= 1", name="sequence"),
        Index(
            "ix_mde_event_document",
            "company_id",
            "inbound_fiscal_document_id",
            "sequence",
        ),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    inbound_fiscal_document_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(6), nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    protocol: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "InboundFiscalDocumentItemModel",
    "InboundFiscalDocumentModel",
    "MdeEventModel",
]

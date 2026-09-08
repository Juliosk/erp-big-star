"""Barcode uniqueness and composite tenant FK are enforced by PostgreSQL."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class ProductBarcodeModel(OptimisticLockMixin, Base):
    __tablename__ = "product_barcode"
    __table_args__ = (
        UniqueConstraint("company_id", "barcode", name="uq_product_barcode_company_value"),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_product_barcode_company_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("barcode_type IN ('EAN', 'DUN', 'INTERNAL')", name="type"),
        CheckConstraint("barcode ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="value"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_product_barcode_company_product", "company_id", "product_id"),
        {"schema": "product"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    barcode_type: Mapped[str] = mapped_column(String(8), nullable=False)
    barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["ProductBarcodeModel"]

"""Inventory lot mapping with composite company/product isolation."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
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


class InventoryLotModel(OptimisticLockMixin, Base):
    """Product lot/batch available to future ledger and reservation slices."""

    __tablename__ = "inventory_lot"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_lot_company_id"),
        UniqueConstraint("company_id", "product_id", "code", name="uq_inventory_lot_product_code"),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_lot_company_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint("status IN ('OPEN', 'QUARANTINED', 'BLOCKED', 'CLOSED')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_inventory_lot_company_product", "company_id", "product_id", "status"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["InventoryLotModel"]

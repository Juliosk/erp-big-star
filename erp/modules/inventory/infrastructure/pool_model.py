"""Inventory pool mapping owned by M5."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class InventoryPoolModel(OptimisticLockMixin, Base):
    """Commercial stock pool partition inside one company catalogue."""

    __tablename__ = "inventory_pool"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_pool_company_id"),
        UniqueConstraint("company_id", "code", name="uq_inventory_pool_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint("kind IN ('MARKETPLACE', 'B2B', 'STORE')", name="kind"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_inventory_pool_company_kind", "company_id", "kind", "code"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["InventoryPoolModel"]

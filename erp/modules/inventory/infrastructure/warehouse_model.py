"""M5 warehouse mappings. Company and branch remain external FKs, not ORM relationships."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class WarehouseModel(OptimisticLockMixin, Base):
    """Company-scoped physical warehouse for M5 inventory operations."""

    __tablename__ = "warehouse"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_warehouse_company_id"),
        UniqueConstraint("company_id", "code", name="uq_inventory_warehouse_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_inventory_warehouse_company_active", "company_id", "active", "code"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.branch.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WarehouseLocationModel(OptimisticLockMixin, Base):
    """Addressable warehouse location, scoped by company and parent warehouse."""

    __tablename__ = "location"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_location_company_id"),
        UniqueConstraint(
            "company_id",
            "warehouse_id",
            "code",
            name="uq_inventory_location_company_warehouse_code",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_location_company_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "parent_location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_location_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint(
            "parent_location_id IS NULL OR parent_location_id <> id",
            name="not_own_parent",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_inventory_location_company_warehouse", "company_id", "warehouse_id", "code"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    parent_location_id: Mapped[UUID | None] = mapped_column(nullable=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["WarehouseLocationModel", "WarehouseModel"]

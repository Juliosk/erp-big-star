"""SQLAlchemy mapping for versioned M5 inventory balances."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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


class InventoryBalanceModel(OptimisticLockMixin, Base):
    """Durable balance row for one company/product/location/pool/state combination."""

    __tablename__ = "inventory_balance"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_balance_company_id"),
        UniqueConstraint(
            "company_id",
            "product_id",
            "warehouse_id",
            "location_id",
            "lot_id",
            "pool_id",
            "state",
            name="uq_inventory_balance_dimensions",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_balance_company_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_balance_company_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_balance_company_location",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_inventory_balance_company_lot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_inventory_balance_company_pool",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "state IN ("
            "'AVAILABLE', 'RESERVED', 'QUARANTINE', 'DAMAGED', 'BLOCKED', "
            "'IN_TRANSIT', 'RECEIVING_STAGE'"
            ")",
            name="state",
        ),
        Index("ix_inventory_balance_company_product", "company_id", "product_id", "state"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    location_id: Mapped[UUID | None] = mapped_column(nullable=True)
    lot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    pool_id: Mapped[UUID | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["InventoryBalanceModel"]

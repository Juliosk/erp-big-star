"""SQLAlchemy mappings for the immutable M5 inventory ledger."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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

from erp.platform.database import Base


class InventoryTransactionModel(Base):
    """Ledger header. Rows are append-only and never updated by repositories."""

    __tablename__ = "inventory_transaction"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_transaction_company_id"),
        CheckConstraint(
            "transaction_type IN ('RECEIPT', 'ISSUE', 'TRANSFER', 'ADJUSTMENT')",
            name="type",
        ),
        CheckConstraint(
            "reference_type ~ '^[A-Z0-9][A-Z0-9_]{1,63}$'",
            name="reference_type_format",
        ),
        Index("ix_inventory_transaction_company_occurred", "company_id", "occurred_at", "id"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[UUID | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class InventoryPostingModel(Base):
    """Ledger line. Signed quantity deltas are immutable inventory facts."""

    __tablename__ = "inventory_posting"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_posting_company_id"),
        UniqueConstraint(
            "company_id",
            "transaction_id",
            "sequence",
            name="uq_inventory_posting_transaction_sequence",
        ),
        ForeignKeyConstraint(
            ["company_id", "transaction_id"],
            ["inventory.inventory_transaction.company_id", "inventory.inventory_transaction.id"],
            name="fk_inventory_posting_transaction",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_posting_company_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_posting_company_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_posting_company_location",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_inventory_posting_company_lot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_inventory_posting_company_pool",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("quantity_delta <> 0", name="quantity_delta_non_zero"),
        CheckConstraint(
            "state IN ("
            "'AVAILABLE', 'RESERVED', 'QUARANTINE', 'DAMAGED', 'BLOCKED', "
            "'IN_TRANSIT', 'RECEIVING_STAGE'"
            ")",
            name="state",
        ),
        Index("ix_inventory_posting_company_product", "company_id", "product_id", "id"),
        Index("ix_inventory_posting_company_transaction", "company_id", "transaction_id"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    location_id: Mapped[UUID | None] = mapped_column(nullable=True)
    lot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    pool_id: Mapped[UUID | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["InventoryPostingModel", "InventoryTransactionModel"]

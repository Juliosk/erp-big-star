"""SQLAlchemy mappings for M5 inventory reservations."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class InventoryReservationModel(OptimisticLockMixin, Base):
    """Reservation aggregate root owned by M5."""

    __tablename__ = "inventory_reservation"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_inventory_reservation_company_id"),
        UniqueConstraint(
            "company_id",
            "reference_type",
            "reference_id",
            name="uq_inventory_reservation_reference",
        ),
        CheckConstraint("reservation_kind IN ('HARD', 'SOFT')", name="kind"),
        CheckConstraint("status IN ('ACTIVE', 'RELEASED', 'EXPIRED')", name="status"),
        CheckConstraint(
            "reference_type ~ '^[A-Z0-9][A-Z0-9_]{1,63}$'",
            name="reference_type_format",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="expiry_after_creation",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_inventory_reservation_company_status", "company_id", "status", "expires_at"),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    reservation_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    allocations: Mapped[list[InventoryReservationAllocationModel]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class InventoryReservationAllocationModel(Base):
    """Dimension-level reserved quantity for a reservation."""

    __tablename__ = "inventory_reservation_allocation"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_inventory_reservation_allocation_company_id",
        ),
        ForeignKeyConstraint(
            ["company_id", "reservation_id"],
            ["inventory.inventory_reservation.company_id", "inventory.inventory_reservation.id"],
            name="fk_inventory_reservation_allocation_reservation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_reservation_allocation_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_reservation_allocation_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_reservation_allocation_location",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_inventory_reservation_allocation_lot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_inventory_reservation_allocation_pool",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "state IN ("
            "'AVAILABLE', 'RESERVED', 'QUARANTINE', 'DAMAGED', 'BLOCKED', "
            "'IN_TRANSIT', 'RECEIVING_STAGE'"
            ")",
            name="state",
        ),
        Index(
            "ix_inventory_reservation_allocation_contention",
            "company_id",
            "product_id",
            "warehouse_id",
            "lot_id",
            "pool_id",
            "state",
        ),
        Index(
            "ix_inventory_reservation_allocation_reservation",
            "company_id",
            "reservation_id",
        ),
        {"schema": "inventory"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    reservation_id: Mapped[UUID] = mapped_column(nullable=False)
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
    reservation: Mapped[InventoryReservationModel] = relationship(back_populates="allocations")


__all__ = ["InventoryReservationAllocationModel", "InventoryReservationModel"]

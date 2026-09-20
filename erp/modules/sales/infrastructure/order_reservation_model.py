"""SQLAlchemy projection linking an M4 order snapshot to its M5 reservation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class SalesOrderReservationModel(OptimisticLockMixin, Base):
    __tablename__ = "sales_order_reservation"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_order_reservation_company_id"),
        UniqueConstraint("company_id", "order_id", name="uq_sales_order_reservation_order"),
        UniqueConstraint(
            "company_id",
            "inventory_reservation_id",
            name="uq_sales_order_reservation_inventory",
        ),
        CheckConstraint(
            "status IN ('REQUESTED', 'HELD', 'RELEASED', 'CANCELLED', 'EXPIRED')",
            name="status",
        ),
        CheckConstraint("order_version >= 1", name="order_version_positive"),
        ForeignKeyConstraint(
            ["company_id", "order_id"],
            ["sales_b2b.sales_order.company_id", "sales_b2b.sales_order.id"],
            name="fk_sales_order_reservation_order",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "inventory_reservation_id"],
            [
                "inventory.inventory_reservation.company_id",
                "inventory.inventory_reservation.id",
            ],
            name="fk_sales_order_reservation_inventory",
            ondelete="RESTRICT",
        ),
        Index("ix_sales_order_reservation_status", "company_id", "status", "created_at"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(nullable=False)
    inventory_reservation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    order_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class SalesOrderReservationLineModel(Base):
    __tablename__ = "sales_order_reservation_line"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id", name="uq_sales_order_reservation_line_company_id"
        ),
        UniqueConstraint(
            "company_id",
            "reservation_id",
            "order_item_id",
            name="uq_sales_order_reservation_line_item",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        ForeignKeyConstraint(
            ["company_id", "reservation_id"],
            [
                "sales_b2b.sales_order_reservation.company_id",
                "sales_b2b.sales_order_reservation.id",
            ],
            name="fk_sales_order_reservation_line_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "order_item_id"],
            ["sales_b2b.sales_order_item.company_id", "sales_b2b.sales_order_item.id"],
            name="fk_sales_order_reservation_line_order_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_sales_order_reservation_line_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pricing_snapshot_id"],
            ["pricing.pricing_snapshot.company_id", "pricing.pricing_snapshot.id"],
            name="fk_sales_order_reservation_line_pricing_snapshot",
            ondelete="RESTRICT",
        ),
        Index("ix_sales_order_reservation_line_parent", "company_id", "reservation_id"),
        {"schema": "sales_b2b"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    reservation_id: Mapped[UUID] = mapped_column(nullable=False)
    order_item_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    pricing_snapshot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["SalesOrderReservationLineModel", "SalesOrderReservationModel"]

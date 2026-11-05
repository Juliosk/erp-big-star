"""Tenant-bound SQLAlchemy mappings for MRP execution history."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_UOMS = "('EA', 'KG', 'G', 'L', 'ML', 'M', 'M2')"


class MRPRunHistoryModel(OptimisticLockMixin, Base):
    __tablename__ = "mrp_run_history"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_mrp_run_company_id"),
        CheckConstraint("horizon_end >= as_of", name="horizon"),
        CheckConstraint("completed_at >= started_at", name="execution_dates"),
        CheckConstraint("status = 'COMPLETED'", name="status"),
        CheckConstraint("char_length(engine_version) BETWEEN 1 AND 32", name="engine_version"),
        CheckConstraint("demand_count >= 1", name="demand_count"),
        CheckConstraint("requirement_count >= 1", name="requirement_count"),
        CheckConstraint("planned_order_count >= 0", name="planned_order_count"),
        CheckConstraint("alert_count >= 0", name="alert_count"),
        CheckConstraint("jsonb_typeof(input_snapshot) = 'object'", name="input_snapshot"),
        CheckConstraint("jsonb_typeof(result_snapshot) = 'object'", name="result_snapshot"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_mrp_run_company_as_of_horizon",
            "company_id",
            "as_of",
            "horizon_end",
            "completed_at",
        ),
        Index(
            "ix_mrp_run_company_completed",
            "company_id",
            "completed_at",
            "id",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    demand_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_count: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class MRPPlannedOrderModel(OptimisticLockMixin, Base):
    __tablename__ = "planned_order"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "mrp_run_id"],
            ["production.mrp_run_history.company_id", "production.mrp_run_history.id"],
            name="fk_planned_order_company_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_planned_order_company_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "converted_production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_planned_order_converted_production_order",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "material_reservation_id"],
            [
                "inventory.inventory_reservation.company_id",
                "inventory.inventory_reservation.id",
            ],
            name="fk_planned_order_material_reservation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id",
            "mrp_run_id",
            "id",
            name="uq_planned_order_company_run_id",
        ),
        UniqueConstraint(
            "company_id",
            "mrp_run_id",
            "sequence",
            name="uq_planned_order_run_sequence",
        ),
        UniqueConstraint(
            "company_id",
            "converted_production_order_id",
            name="uq_planned_order_converted_production_order",
        ),
        UniqueConstraint(
            "company_id",
            "material_reservation_id",
            name="uq_planned_order_material_reservation",
        ),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint("order_type IN ('MANUFACTURE', 'PURCHASE')", name="order_type"),
        CheckConstraint("status IN ('PLANNED', 'CONVERTED', 'CANCELLED')", name="status"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint(f"uom IN {_UOMS}", name="uom"),
        CheckConstraint("release_on <= due_on", name="dates"),
        CheckConstraint(
            "jsonb_typeof(source_ids) = 'array' AND jsonb_array_length(source_ids) > 0",
            name="source_ids",
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "(status = 'CONVERTED' AND converted_production_order_id IS NOT NULL "
            "AND material_reservation_id IS NOT NULL AND converted_at IS NOT NULL "
            "AND converted_by IS NOT NULL) OR (status <> 'CONVERTED' "
            "AND converted_production_order_id IS NULL AND material_reservation_id IS NULL "
            "AND converted_at IS NULL AND converted_by IS NULL)",
            name="conversion_evidence",
        ),
        Index(
            "ix_planned_order_company_status_dates",
            "company_id",
            "status",
            "release_on",
            "due_on",
        ),
        Index(
            "ix_planned_order_company_product_due",
            "company_id",
            "product_id",
            "due_on",
        ),
        Index(
            "ix_planned_order_company_conversion",
            "company_id",
            "status",
            "converted_at",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    mrp_run_id: Mapped[UUID] = mapped_column(primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(12), nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    release_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    converted_production_order_id: Mapped[UUID | None] = mapped_column(nullable=True)
    material_reservation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["MRPPlannedOrderModel", "MRPRunHistoryModel"]

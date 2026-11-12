"""Tenant-bound SQLAlchemy mappings for production orders."""

from datetime import date, datetime
from decimal import Decimal
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_UOMS = "('EA', 'KG', 'G', 'L', 'ML', 'M', 'M2')"
_ORDER_STATUSES = "('DRAFT', 'RELEASED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')"
_OPERATION_STATUSES = "('PENDING', 'IN_PROGRESS', 'COMPLETED')"


class ProductionOrderModel(OptimisticLockMixin, Base):
    __tablename__ = "production_order"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_production_order_company_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id", "bom_version_code"],
            [
                "production.bom_header.company_id",
                "production.bom_header.product_id",
                "production.bom_header.version_code",
            ],
            name="fk_production_order_bom_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id", "routing_version_code"],
            [
                "production.routing_header.company_id",
                "production.routing_header.product_id",
                "production.routing_header.version_code",
            ],
            name="fk_production_order_routing_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_production_order_company_id"),
        UniqueConstraint(
            "company_id",
            "order_number",
            name="uq_production_order_company_number",
        ),
        CheckConstraint(
            "order_number ~ '^[A-Z0-9][A-Z0-9._/-]{0,39}$'",
            name="order_number",
        ),
        CheckConstraint(f"status IN {_ORDER_STATUSES}", name="status"),
        CheckConstraint("planned_quantity > 0", name="planned_quantity"),
        CheckConstraint(f"planned_uom IN {_UOMS}", name="planned_uom"),
        CheckConstraint("due_on >= planned_start_on", name="dates"),
        CheckConstraint("bom_engineering_revision >= 1", name="bom_revision"),
        CheckConstraint("bom_record_version >= 1", name="bom_record_version"),
        CheckConstraint("routing_engineering_revision >= 1", name="routing_revision"),
        CheckConstraint("routing_record_version >= 1", name="routing_record_version"),
        CheckConstraint("engineering_output_quantity > 0", name="engineering_quantity"),
        CheckConstraint(f"engineering_output_uom IN {_UOMS}", name="engineering_uom"),
        CheckConstraint("jsonb_typeof(output_lots) = 'array'", name="output_lots"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_production_order_company_status_dates",
            "company_id",
            "status",
            "planned_start_on",
            "due_on",
        ),
        Index(
            "ix_production_order_company_product_status",
            "company_id",
            "product_id",
            "status",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    order_number: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    planned_uom: Mapped[str] = mapped_column(String(12), nullable=False)
    planned_start_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    bom_version_code: Mapped[str] = mapped_column(String(32), nullable=False)
    bom_engineering_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    bom_effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    bom_effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    bom_record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_version_code: Mapped[str] = mapped_column(String(32), nullable=False)
    routing_engineering_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    routing_effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    routing_record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engineering_output_quantity: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), nullable=False
    )
    engineering_output_uom: Mapped[str] = mapped_column(String(12), nullable=False)
    engineering_approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    engineering_approved_by: Mapped[UUID] = mapped_column(nullable=False)
    output_lots: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[UUID | None] = mapped_column()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[UUID | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[UUID | None] = mapped_column()
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[UUID | None] = mapped_column()
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class ProductionOrderItemPlanModel(OptimisticLockMixin, Base):
    __tablename__ = "production_order_item_plan"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_production_order_item_plan_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "component_product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_production_order_item_plan_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id",
            "production_order_id",
            "sequence",
            name="uq_production_order_item_plan_sequence",
        ),
        UniqueConstraint(
            "company_id",
            "production_order_id",
            "component_product_id",
            name="uq_production_order_item_plan_product",
        ),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint("planned_quantity > 0", name="planned_quantity"),
        CheckConstraint(f"uom IN {_UOMS}", name="uom"),
        CheckConstraint("jsonb_typeof(consumptions) = 'array'", name="consumptions"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_production_order_item_plan_order",
            "company_id",
            "production_order_id",
            "sequence",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    production_order_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    component_product_id: Mapped[UUID] = mapped_column(nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(12), nullable=False)
    consumptions: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class ProductionOrderOperationExecutionModel(OptimisticLockMixin, Base):
    __tablename__ = "production_order_operation_execution"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_production_order_operation_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "assigned_work_center_code"],
            ["production.work_center.company_id", "production.work_center.code"],
            name="fk_production_order_operation_work_center",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id",
            "production_order_id",
            "sequence",
            name="uq_production_order_operation_sequence",
        ),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="name",
        ),
        CheckConstraint(f"status IN {_OPERATION_STATUSES}", name="status"),
        CheckConstraint(
            "jsonb_typeof(allowed_work_centers) = 'array' "
            "AND jsonb_array_length(allowed_work_centers) > 0",
            name="allowed_work_centers",
        ),
        CheckConstraint(
            "jsonb_typeof(required_capabilities) = 'array'",
            name="required_capabilities",
        ),
        CheckConstraint(
            "assigned_work_center_capabilities IS NULL "
            "OR jsonb_typeof(assigned_work_center_capabilities) = 'array'",
            name="assigned_capabilities",
        ),
        CheckConstraint(
            "assigned_work_center_version IS NULL OR assigned_work_center_version >= 1",
            name="assigned_version",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_production_order_operation_order",
            "company_id",
            "production_order_id",
            "sequence",
            "status",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    production_order_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    allowed_work_centers: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    required_capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    assigned_work_center_code: Mapped[str | None] = mapped_column(String(32))
    assigned_work_center_capabilities: Mapped[list[str] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    assigned_work_center_version: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[UUID | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[UUID | None] = mapped_column()


__all__ = [
    "ProductionOrderItemPlanModel",
    "ProductionOrderModel",
    "ProductionOrderOperationExecutionModel",
]

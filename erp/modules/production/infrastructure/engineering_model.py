"""Tenant-bound SQLAlchemy mappings for Production engineering."""

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_UOMS = "('EA', 'KG', 'G', 'L', 'ML', 'M', 'M2')"


class WorkCenterModel(OptimisticLockMixin, Base):
    __tablename__ = "work_center"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name="code"),
        CheckConstraint("jsonb_typeof(capabilities) = 'array'", name="capabilities"),
        CheckConstraint("version >= 1", name="version"),
        {"schema": "production"},
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class BomHeaderModel(OptimisticLockMixin, Base):
    __tablename__ = "bom_header"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_bom_header_company_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_bom_header_company_id"),
        UniqueConstraint(
            "company_id",
            "product_id",
            "version_code",
            name="uq_bom_header_company_product_version",
        ),
        CheckConstraint(
            "version_code ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name="version_code",
        ),
        CheckConstraint("engineering_revision >= 1", name="engineering_revision"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="effective_range",
        ),
        CheckConstraint("output_quantity > 0", name="output_quantity"),
        CheckConstraint(f"output_uom IN {_UOMS}", name="output_uom"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_bom_header_company_product",
            "company_id",
            "product_id",
            "version_code",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    version_code: Mapped[str] = mapped_column(String(32), nullable=False)
    engineering_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    output_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    output_uom: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class BomComponentModel(OptimisticLockMixin, Base):
    __tablename__ = "bom_component"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "bom_id"],
            ["production.bom_header.company_id", "production.bom_header.id"],
            name="fk_bom_component_company_header",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "component_product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_bom_component_company_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id", "bom_id", "sequence", name="uq_bom_component_sequence"
        ),
        UniqueConstraint(
            "company_id",
            "bom_id",
            "component_product_id",
            name="uq_bom_component_product",
        ),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint("quantity_per_output > 0", name="quantity"),
        CheckConstraint(f"uom IN {_UOMS}", name="uom"),
        CheckConstraint("scrap_rate >= 0 AND scrap_rate < 1", name="scrap"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_bom_component_company_product",
            "company_id",
            "component_product_id",
            "bom_id",
        ),
        Index(
            "ix_bom_component_company_header",
            "company_id",
            "bom_id",
            "sequence",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    bom_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    component_product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity_per_output: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(12), nullable=False)
    scrap_rate: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)


class RoutingHeaderModel(OptimisticLockMixin, Base):
    __tablename__ = "routing_header"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_routing_header_company_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_routing_header_company_id"),
        UniqueConstraint(
            "company_id",
            "product_id",
            "version_code",
            name="uq_routing_header_company_product_version",
        ),
        CheckConstraint(
            "version_code ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name="version_code",
        ),
        CheckConstraint("engineering_revision >= 1", name="engineering_revision"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="effective_range",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_routing_header_company_product",
            "company_id",
            "product_id",
            "version_code",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    version_code: Mapped[str] = mapped_column(String(32), nullable=False)
    engineering_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class RoutingOperationModel(OptimisticLockMixin, Base):
    __tablename__ = "routing_operation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "routing_id"],
            ["production.routing_header.company_id", "production.routing_header.id"],
            name="fk_routing_operation_company_header",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "routing_id",
            "sequence",
            name="uq_routing_operation_sequence",
        ),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="name",
        ),
        CheckConstraint("setup_minutes >= 0", name="setup_minutes"),
        CheckConstraint("run_minutes_per_unit > 0", name="run_minutes_per_unit"),
        CheckConstraint(
            "jsonb_typeof(allowed_work_centers) = 'array' "
            "AND jsonb_array_length(allowed_work_centers) > 0",
            name="allowed_work_centers",
        ),
        CheckConstraint(
            "jsonb_typeof(required_capabilities) = 'array'",
            name="required_capabilities",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_routing_operation_company_header",
            "company_id",
            "routing_id",
            "sequence",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    routing_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    setup_minutes: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    run_minutes_per_unit: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    allowed_work_centers: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    required_capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


__all__ = [
    "BomComponentModel",
    "BomHeaderModel",
    "RoutingHeaderModel",
    "RoutingOperationModel",
    "WorkCenterModel",
]


"""SQLAlchemy mappings for M9 price lists and initial pricing snapshots."""

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
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class PriceListModel(OptimisticLockMixin, Base):
    """Company-owned commercial price list."""

    __tablename__ = "price_list"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_list_company_id"),
        UniqueConstraint("company_id", "code", name="uq_price_list_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint(
            "price_type IN ('BASE', 'CHANNEL', 'CUSTOMER_GROUP')",
            name="price_type",
        ),
        CheckConstraint("currency = 'BRL'", name="currency_brl"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_price_list_company_status", "company_id", "status", "code"),
        {"schema": "pricing"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    price_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)
    versions: Mapped[list[PriceListVersionModel]] = relationship(
        back_populates="price_list",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class PriceListVersionModel(OptimisticLockMixin, Base):
    """Versioned set of prices, activated atomically by M9."""

    __tablename__ = "price_list_version"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_list_version_company_id"),
        UniqueConstraint(
            "company_id",
            "price_list_id",
            "version_number",
            name="uq_price_list_version_number",
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'EXPIRED')",
            name="status",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        CheckConstraint("source ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name="source_format"),
        CheckConstraint(
            "status != 'ACTIVE' OR activated_at IS NOT NULL",
            name="active_requires_activation",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "price_list_id"],
            ["pricing.price_list.company_id", "pricing.price_list.id"],
            name="fk_price_list_version_price_list",
            ondelete="RESTRICT",
        ),
        Index("ix_price_list_version_company_status", "company_id", "status", "valid_from"),
        {"schema": "pricing"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    price_list_id: Mapped[UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)
    price_list: Mapped[PriceListModel] = relationship(back_populates="versions")
    items: Mapped[list[PriceListItemModel]] = relationship(
        back_populates="price_list_version",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class PriceListItemModel(Base):
    """Product-level approved price inside a price-list version."""

    __tablename__ = "price_list_item"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_list_item_company_id"),
        UniqueConstraint(
            "company_id",
            "price_list_version_id",
            "product_id",
            name="uq_price_list_item_product",
        ),
        CheckConstraint("price_amount >= 0", name="price_non_negative"),
        CheckConstraint("minimum_price_amount IS NULL OR minimum_price_amount >= 0", name="min_non_negative"),
        CheckConstraint(
            "minimum_price_amount IS NULL OR minimum_price_amount <= price_amount",
            name="min_not_above_price",
        ),
        CheckConstraint(
            "target_margin IS NULL OR (target_margin >= 0 AND target_margin <= 1)",
            name="target_margin_range",
        ),
        CheckConstraint("currency = 'BRL'", name="currency_brl"),
        ForeignKeyConstraint(
            ["company_id", "price_list_version_id"],
            ["pricing.price_list_version.company_id", "pricing.price_list_version.id"],
            name="fk_price_list_item_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_price_list_item_product",
            ondelete="RESTRICT",
        ),
        Index("ix_price_list_item_product", "company_id", "product_id"),
        {"schema": "pricing"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    price_list_version_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    minimum_price_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    target_margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    price_list_version: Mapped[PriceListVersionModel] = relationship(back_populates="items")


class MinimumMarginPolicyModel(OptimisticLockMixin, Base):
    """Minimum-margin guardrail used by the initial floor-price resolver."""

    __tablename__ = "minimum_margin_policy"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_minimum_margin_policy_company_id"),
        UniqueConstraint("company_id", "code", name="uq_minimum_margin_policy_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint(
            "minimum_margin >= 0 AND minimum_margin <= 1",
            name="minimum_margin_range",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        {"schema": "pricing"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    minimum_margin: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PricingSnapshotModel(Base):
    """Immutable snapshot of one pricing decision."""

    __tablename__ = "pricing_snapshot"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_pricing_snapshot_company_id"),
        CheckConstraint("calculated_price_amount >= 0", name="calculated_price_non_negative"),
        CheckConstraint("rounded_price_amount >= 0", name="rounded_price_non_negative"),
        CheckConstraint("currency = 'BRL'", name="currency_brl"),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_pricing_snapshot_product",
            ondelete="RESTRICT",
        ),
        Index("ix_pricing_snapshot_product", "company_id", "product_id", "created_at"),
        {"schema": "pricing"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    price_list_id: Mapped[UUID | None] = mapped_column(nullable=True)
    price_list_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    cost_reference: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    tax_reference: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    commission_reference: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    fee_reference: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    freight_reference: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    target_margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    minimum_margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    calculated_price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    rounded_price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "MinimumMarginPolicyModel",
    "PriceListItemModel",
    "PriceListModel",
    "PriceListVersionModel",
    "PricingSnapshotModel",
]

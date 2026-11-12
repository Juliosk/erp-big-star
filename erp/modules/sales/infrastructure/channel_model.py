"""Tenant-bound SQLAlchemy mappings for external sales channels."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_MARKETPLACES = "('MERCADO_LIVRE', 'SHOPEE', 'NUVEMSHOP')"
_STATUSES = "('PENDING', 'PAID', 'SHIPPED', 'CANCELLED')"


class SalesChannelConfigModel(OptimisticLockMixin, Base):
    __tablename__ = "sales_channel_config"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_channel_config_company_id"),
        UniqueConstraint(
            "company_id",
            "marketplace",
            "account_id",
            name="uq_sales_channel_config_account",
        ),
        CheckConstraint(f"marketplace IN {_MARKETPLACES}", name="marketplace"),
        CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 128 "
            "AND display_name = btrim(display_name)",
            name="display_name",
        ),
        CheckConstraint(
            "length(btrim(credential_reference)) BETWEEN 1 AND 255 "
            "AND credential_reference = btrim(credential_reference)",
            name="credential_reference",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_sales_channel_config_company_active",
            "company_id",
            "active",
            "marketplace",
        ),
        {"schema": "sales"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    marketplace: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class ExternalOrderMappingModel(OptimisticLockMixin, Base):
    """Normalized De/Para from an external listing/variation to an M2 product."""

    __tablename__ = "external_order_mapping"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "channel_config_id"],
            ["sales.sales_channel_config.company_id", "sales.sales_channel_config.id"],
            name="fk_external_order_mapping_channel_config",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_external_order_mapping_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_external_order_mapping_company_id"),
        UniqueConstraint(
            "company_id",
            "channel_config_id",
            "listing_id",
            "variation_id",
            name="uq_external_order_mapping_listing",
        ),
        CheckConstraint(f"marketplace IN {_MARKETPLACES}", name="marketplace"),
        CheckConstraint(
            "length(btrim(listing_id)) BETWEEN 1 AND 128 "
            "AND listing_id = btrim(listing_id)",
            name="listing_id",
        ),
        CheckConstraint(
            "length(btrim(variation_id)) BETWEEN 1 AND 128 "
            "AND variation_id = btrim(variation_id)",
            name="variation_id",
        ),
        CheckConstraint(
            "length(btrim(external_sku)) BETWEEN 1 AND 128 "
            "AND external_sku = btrim(external_sku)",
            name="external_sku",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_external_order_mapping_company_sku",
            "company_id",
            "channel_config_id",
            "external_sku",
        ),
        Index(
            "ix_external_order_mapping_company_product", "company_id", "product_id"
        ),
        {"schema": "sales"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    channel_config_id: Mapped[UUID] = mapped_column(nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    marketplace: Mapped[str] = mapped_column(String(24), nullable=False)
    listing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    variation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_sku: Mapped[str] = mapped_column(String(128), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class ChannelSalesOrderModel(OptimisticLockMixin, Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "channel_config_id"],
            ["sales.sales_channel_config.company_id", "sales.sales_channel_config.id"],
            name="fk_sales_order_channel_config",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id", "id", name="uq_sales_order_channel_company_id"
        ),
        UniqueConstraint(
            "company_id",
            "marketplace",
            "account_id",
            "external_order_id",
            name="uq_sales_order_external_identity",
        ),
        CheckConstraint(f"marketplace IN {_MARKETPLACES}", name="marketplace"),
        CheckConstraint(f"status IN {_STATUSES}", name="channel_status"),
        CheckConstraint("currency = 'BRL'", name="channel_currency"),
        CheckConstraint(
            "length(btrim(external_order_id)) BETWEEN 1 AND 128 "
            "AND external_order_id = btrim(external_order_id)",
            name="external_order_id",
        ),
        CheckConstraint(
            "merchandise_amount >= 0 AND freight_amount >= 0 "
            "AND discount_amount >= 0 AND total_amount >= 0",
            name="channel_amounts",
        ),
        CheckConstraint(
            "total_amount = merchandise_amount - discount_amount + freight_amount",
            name="channel_total",
        ),
        CheckConstraint(
            "jsonb_typeof(items) = 'array' AND jsonb_array_length(items) > 0",
            name="channel_items",
        ),
        CheckConstraint(
            "source_payload_hash ~ '^[0-9a-f]{64}$'", name="source_payload_hash"
        ),
        CheckConstraint("version >= 1", name="channel_version"),
        Index(
            "ix_sales_order_channel_company_status", "company_id", "status", "created_at"
        ),
        Index(
            "ix_sales_order_channel_company_external",
            "company_id",
            "marketplace",
            "account_id",
            "external_order_id",
        ),
        {"schema": "sales"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    channel_config_id: Mapped[UUID] = mapped_column(nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    marketplace: Mapped[str] = mapped_column(String(24), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchandise_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    items: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    source_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "ChannelSalesOrderModel",
    "ExternalOrderMappingModel",
    "SalesChannelConfigModel",
]

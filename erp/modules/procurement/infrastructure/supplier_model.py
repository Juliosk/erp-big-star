"""M6-owned SQLAlchemy mappings for suppliers and their establishments."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class SupplierModel(OptimisticLockMixin, Base):
    """Company-owned supplier master record."""

    __tablename__ = "supplier"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_supplier_company_id"),
        UniqueConstraint(
            "company_id",
            "identity_kind",
            "identity_country_code",
            "identity_value",
            name="uq_supplier_fiscal_identity",
        ),
        CheckConstraint("kind IN ('INDIVIDUAL', 'COMPANY', 'FOREIGN')", name="kind"),
        CheckConstraint(
            "identity_kind IN ('CPF', 'CNPJ', 'FOREIGN_REGISTRATION')",
            name="identity_kind",
        ),
        CheckConstraint(
            "(kind = 'INDIVIDUAL' AND identity_kind = 'CPF' AND identity_country_code = 'BR') "
            "OR (kind = 'COMPANY' AND identity_kind = 'CNPJ' AND identity_country_code = 'BR') "
            "OR (kind = 'FOREIGN' AND identity_kind = 'FOREIGN_REGISTRATION' "
            "AND identity_country_code <> 'BR')",
            name="kind_identity_match",
        ),
        CheckConstraint("identity_country_code ~ '^[A-Z]{2}$'", name="identity_country_code"),
        CheckConstraint(
            "(identity_kind = 'CPF' AND identity_value ~ '^[0-9]{11}$') OR "
            "(identity_kind = 'CNPJ' AND identity_value ~ '^[0-9]{14}$') OR "
            "(identity_kind = 'FOREIGN_REGISTRATION' AND "
            "identity_value ~ '^[A-Z0-9][A-Z0-9 ._/-]{1,59}$')",
            name="identity_value_format",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'BLOCKED')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_supplier_company_legal_name", "company_id", "legal_name", "id"),
        Index("ix_supplier_company_status", "company_id", "status"),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identity_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    identity_value: Mapped[str] = mapped_column(String(60), nullable=False)
    identity_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class SupplierSiteModel(OptimisticLockMixin, Base):
    """Tenant-bound physical or commercial establishment of a supplier."""

    __tablename__ = "supplier_site"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_supplier_site_company_supplier",
            ondelete="CASCADE",
        ),
        UniqueConstraint("company_id", "id", name="uq_supplier_site_company_id"),
        UniqueConstraint("company_id", "code", name="uq_supplier_site_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="code_format"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code"),
        CheckConstraint(
            "(country_code = 'BR' AND state ~ '^[A-Z]{2}$' AND postal_code ~ '^[0-9]{8}$') "
            "OR country_code <> 'BR'",
            name="brazilian_address",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_supplier_site_supplier", "company_id", "supplier_id", "code", "id"),
        Index(
            "uq_supplier_site_primary",
            "company_id",
            "supplier_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
        {"schema": "procurement"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    line1: Mapped[str] = mapped_column(String(180), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(180), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["SupplierModel", "SupplierSiteModel"]

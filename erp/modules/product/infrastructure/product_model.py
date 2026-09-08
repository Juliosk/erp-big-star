"""M2-owned SQLAlchemy mapping. Company is a Foundation FK, not an ORM relationship."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class ProductModel(OptimisticLockMixin, Base):
    """The first company-owned product master table."""

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_product_company_id"),
        UniqueConstraint("sku", name="uq_product_sku"),
        UniqueConstraint("company_id", "code", name="uq_product_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint("sku ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="sku_format"),
        CheckConstraint("uom ~ '^[A-Z0-9][A-Z0-9._-]{0,11}$'", name="uom_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 200 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint("product_type IN ('PA', 'PI', 'MA', 'AUX', 'EMB', 'KIT')", name="type"),
        CheckConstraint(
            "lifecycle IN ('EM_DESENVOLVIMENTO', 'EM_HOMOLOGACAO', 'ATIVO', 'FORA_DE_LINHA')",
            name="lifecycle",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_product_company_code", "company_id", "code", "id"),
        Index("ix_product_company_lifecycle", "company_id", "lifecycle"),
        {"schema": "product"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_type: Mapped[str] = mapped_column(String(3), nullable=False)
    uom: Mapped[str] = mapped_column(String(12), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["ProductModel"]

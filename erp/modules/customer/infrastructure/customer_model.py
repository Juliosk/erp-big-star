"""M14-owned SQLAlchemy mapping. Company is an M1 FK, not an ORM relationship."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class CustomerModel(OptimisticLockMixin, Base):
    """Company-owned customer golden record."""

    __tablename__ = "customer"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_customer_company_id"),
        UniqueConstraint(
            "company_id", "identity_type", "identity_value", name="uq_customer_identity"
        ),
        CheckConstraint("customer_type IN ('INDIVIDUAL', 'COMPANY')", name="type"),
        CheckConstraint("identity_type IN ('CPF', 'CNPJ')", name="identity_type"),
        CheckConstraint(
            "(customer_type = 'INDIVIDUAL' AND identity_type = 'CPF') OR "
            "(customer_type = 'COMPANY' AND identity_type = 'CNPJ')",
            name="type_identity_match",
        ),
        CheckConstraint(
            "(identity_type = 'CPF' AND identity_value ~ '^[0-9]{11}$') OR "
            "(identity_type = 'CNPJ' AND identity_value ~ '^[0-9]{14}$')",
            name="identity_value_format",
        ),
        CheckConstraint(
            "char_length(btrim(legal_name)) BETWEEN 1 AND 200 AND legal_name = btrim(legal_name)",
            name="legal_name_length",
        ),
        CheckConstraint(
            "trade_name IS NULL OR "
            "(char_length(btrim(trade_name)) BETWEEN 1 AND 200 AND trade_name = btrim(trade_name))",
            name="trade_name_length",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'BLOCKED')", name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_customer_company_legal_name", "company_id", "legal_name", "id"),
        Index("ix_customer_company_status", "company_id", "status"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    customer_type: Mapped[str] = mapped_column(String(10), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(4), nullable=False)
    identity_value: Mapped[str] = mapped_column(String(14), nullable=False)
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


__all__ = ["CustomerModel"]

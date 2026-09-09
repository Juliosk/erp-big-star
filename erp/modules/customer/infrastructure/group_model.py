"""SQLAlchemy mappings for M14 customer groups and memberships."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class CustomerGroupModel(OptimisticLockMixin, Base):
    __tablename__ = "customer_group"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_customer_group_company_id"),
        UniqueConstraint("company_id", "code", name="uq_customer_group_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'", name="code"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 120 AND name = btrim(name)", name="name"),
        CheckConstraint(
            "description IS NULL OR "
            "(char_length(description) BETWEEN 1 AND 500 AND description = btrim(description))",
            name="description",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_customer_group_company_name", "company_id", "name", "id"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class CustomerGroupMemberModel(Base):
    __tablename__ = "customer_group_member"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_group_member_company_customer",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "customer_group_id"],
            ["crm.customer_group.company_id", "crm.customer_group.id"],
            name="fk_customer_group_member_company_group",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "customer_id",
            "customer_group_id",
            name="uq_customer_group_member",
        ),
        Index("ix_customer_group_member_customer", "company_id", "customer_id", "id"),
        Index("ix_customer_group_member_group", "company_id", "customer_group_id", "id"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    customer_id: Mapped[UUID] = mapped_column(nullable=False)
    customer_group_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["CustomerGroupMemberModel", "CustomerGroupModel"]

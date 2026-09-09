"""M14 SQLAlchemy mappings for customer contacts and addresses."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class CustomerContactModel(Base):
    """Multiple company-scoped contacts for one M14 customer."""

    __tablename__ = "customer_contact"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_contact_company_customer",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "company_id",
            "customer_id",
            "role",
            "kind",
            "value",
            name="uq_customer_contact_value",
        ),
        CheckConstraint("role IN ('BILLING', 'SHIPPING', 'COMMERCIAL', 'FISCAL')", name="role"),
        CheckConstraint("kind IN ('EMAIL', 'PHONE')", name="kind"),
        CheckConstraint(
            "char_length(value) BETWEEN 3 AND 180 AND value = btrim(value)", name="value"
        ),
        CheckConstraint(
            "name IS NULL OR (char_length(name) BETWEEN 1 AND 120 AND name = btrim(name))",
            name="name",
        ),
        Index("ix_customer_contact_customer", "company_id", "customer_id", "role", "id"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    customer_id: Mapped[UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[str] = mapped_column(String(180), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class CustomerAddressModel(Base):
    """Multiple company-scoped addresses for one M14 customer."""

    __tablename__ = "customer_address"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_address_company_customer",
            ondelete="CASCADE",
        ),
        CheckConstraint("role IN ('BILLING', 'SHIPPING', 'COMMERCIAL', 'FISCAL')", name="role"),
        CheckConstraint(
            "char_length(line1) BETWEEN 1 AND 180 AND line1 = btrim(line1)", name="line1"
        ),
        CheckConstraint(
            "line2 IS NULL OR (char_length(line2) BETWEEN 1 AND 180 AND line2 = btrim(line2))",
            name="line2",
        ),
        CheckConstraint(
            "district IS NULL OR "
            "(char_length(district) BETWEEN 1 AND 120 AND district = btrim(district))",
            name="district",
        ),
        CheckConstraint("char_length(city) BETWEEN 1 AND 120 AND city = btrim(city)", name="city"),
        CheckConstraint("state ~ '^[A-Z]{2}$'", name="state"),
        CheckConstraint("postal_code ~ '^[0-9]{8}$'", name="postal_code"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code"),
        Index("ix_customer_address_customer", "company_id", "customer_id", "role", "id"),
        {"schema": "crm"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    customer_id: Mapped[UUID] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    line1: Mapped[str] = mapped_column(String(180), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(8), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(180), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["CustomerAddressModel", "CustomerContactModel"]

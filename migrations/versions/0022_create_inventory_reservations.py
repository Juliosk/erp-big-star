"""Create M5 inventory reservation tables.

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add reservation aggregate and company-scoped allocation dimensions."""
    op.create_table(
        "inventory_reservation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_kind", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "reservation_kind IN ('HARD', 'SOFT')",
            name=op.f("ck_inventory_reservation_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'RELEASED', 'EXPIRED')",
            name=op.f("ck_inventory_reservation_status"),
        ),
        sa.CheckConstraint(
            "reference_type ~ '^[A-Z0-9][A-Z0-9_]{1,63}$'",
            name=op.f("ck_inventory_reservation_reference_type_format"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name=op.f("ck_inventory_reservation_expiry_after_creation"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_inventory_reservation_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_inventory_reservation_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_reservation")),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name=op.f("uq_inventory_reservation_company_id"),
        ),
        sa.UniqueConstraint(
            "company_id",
            "reference_type",
            "reference_id",
            name=op.f("uq_inventory_reservation_reference"),
        ),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_reservation_company_status",
        "inventory_reservation",
        ["company_id", "status", "expires_at"],
        schema="inventory",
    )
    op.create_table(
        "inventory_reservation_allocation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_inventory_reservation_allocation_qty")),
        sa.CheckConstraint(
            "state IN ("
            "'AVAILABLE', 'RESERVED', 'QUARANTINE', 'DAMAGED', 'BLOCKED', "
            "'IN_TRANSIT', 'RECEIVING_STAGE'"
            ")",
            name=op.f("ck_inventory_reservation_allocation_state"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "reservation_id"],
            ["inventory.inventory_reservation.company_id", "inventory.inventory_reservation.id"],
            name=op.f("fk_inventory_reservation_allocation_reservation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name=op.f("fk_inventory_reservation_allocation_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name=op.f("fk_inventory_reservation_allocation_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name=op.f("fk_inventory_reservation_allocation_location"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name=op.f("fk_inventory_reservation_allocation_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name=op.f("fk_inventory_reservation_allocation_pool"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_reservation_allocation")),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name=op.f("uq_inventory_reservation_allocation_company_id"),
        ),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_reservation_allocation_contention",
        "inventory_reservation_allocation",
        ["company_id", "product_id", "warehouse_id", "lot_id", "pool_id", "state"],
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_reservation_allocation_reservation",
        "inventory_reservation_allocation",
        ["company_id", "reservation_id"],
        schema="inventory",
    )


def downgrade() -> None:
    """Destructive for reservation data; use only with explicit approval."""
    op.drop_table("inventory_reservation_allocation", schema="inventory")
    op.drop_table("inventory_reservation", schema="inventory")

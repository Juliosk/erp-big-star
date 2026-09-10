"""Create versioned M5 inventory balances.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add durable stock balances derived transactionally from ledger postings."""
    op.create_table(
        "inventory_balance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_balance")),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_balance_company_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_balance_company_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_balance_company_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_inventory_balance_company_lot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_inventory_balance_company_pool",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_balance_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "product_id",
            "warehouse_id",
            "location_id",
            "lot_id",
            "pool_id",
            "state",
            name="uq_inventory_balance_dimensions",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            "quantity >= 0",
            name=op.f("ck_inventory_balance_quantity_non_negative"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_inventory_balance_version_positive")),
        sa.CheckConstraint(
            "state IN ("
            "'AVAILABLE', 'RESERVED', 'QUARANTINE', 'DAMAGED', 'BLOCKED', "
            "'IN_TRANSIT', 'RECEIVING_STAGE'"
            ")",
            name=op.f("ck_inventory_balance_state"),
        ),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_balance_company_product",
        "inventory_balance",
        ["company_id", "product_id", "state"],
        schema="inventory",
    )


def downgrade() -> None:
    """Destructive for M5 balance data; use only with explicit approval and backup."""
    op.drop_table("inventory_balance", schema="inventory")

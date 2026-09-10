"""Create immutable M5 inventory ledger structures.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add append-only transaction and posting facts for M5 stock movements."""
    op.create_table(
        "inventory_transaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_type", sa.String(32), nullable=False),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_transaction")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_inventory_transaction_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_transaction_company_id"),
        sa.CheckConstraint(
            "transaction_type IN ('RECEIPT', 'ISSUE', 'TRANSFER', 'ADJUSTMENT')",
            name=op.f("ck_inventory_transaction_type"),
        ),
        sa.CheckConstraint(
            "reference_type ~ '^[A-Z0-9][A-Z0-9_]{1,63}$'",
            name=op.f("ck_inventory_transaction_reference_type_format"),
        ),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_transaction_company_occurred",
        "inventory_transaction",
        ["company_id", "occurred_at", "id"],
        schema="inventory",
    )
    op.create_table(
        "inventory_posting",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_posting")),
        sa.ForeignKeyConstraint(
            ["company_id", "transaction_id"],
            ["inventory.inventory_transaction.company_id", "inventory.inventory_transaction.id"],
            name="fk_inventory_posting_transaction",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_posting_company_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_posting_company_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_posting_company_location",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_inventory_posting_company_lot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_inventory_posting_company_pool",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_posting_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "transaction_id",
            "sequence",
            name="uq_inventory_posting_transaction_sequence",
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_inventory_posting_sequence_positive")),
        sa.CheckConstraint(
            "quantity_delta <> 0",
            name=op.f("ck_inventory_posting_quantity_delta_non_zero"),
        ),
        sa.CheckConstraint(
            "state IN ("
            "'AVAILABLE', 'RESERVED', 'QUARANTINE', 'DAMAGED', 'BLOCKED', "
            "'IN_TRANSIT', 'RECEIVING_STAGE'"
            ")",
            name=op.f("ck_inventory_posting_state"),
        ),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_posting_company_product",
        "inventory_posting",
        ["company_id", "product_id", "id"],
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_posting_company_transaction",
        "inventory_posting",
        ["company_id", "transaction_id"],
        schema="inventory",
    )
    op.execute(
        """
        CREATE FUNCTION inventory.reject_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('erp.allow_ledger_cleanup', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'inventory ledger is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table_name in ("inventory_transaction", "inventory_posting"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only_update
            BEFORE UPDATE ON inventory.{table_name}
            FOR EACH ROW EXECUTE FUNCTION inventory.reject_ledger_mutation();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only_delete
            BEFORE DELETE ON inventory.{table_name}
            FOR EACH ROW EXECUTE FUNCTION inventory.reject_ledger_mutation();
            """
        )


def downgrade() -> None:
    """Destructive for M5 ledger data; use only with explicit approval and backup."""
    for table_name in ("inventory_posting", "inventory_transaction"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_delete ON inventory.{table_name}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_update ON inventory.{table_name}"
        )
    op.drop_table("inventory_posting", schema="inventory")
    op.drop_table("inventory_transaction", schema="inventory")
    op.execute("DROP FUNCTION IF EXISTS inventory.reject_ledger_mutation()")

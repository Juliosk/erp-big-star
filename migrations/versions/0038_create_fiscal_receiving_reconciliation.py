"""Create fiscal and physical receiving reconciliation.

Revision ID: 0038
Revises: 0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "receiving_reconciliation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_fiscal_document_id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("financial_blocked", sa.Boolean(), nullable=False),
        sa.Column("physical_pending", sa.Boolean(), nullable=False),
        sa.Column(
            "inventory_transaction_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DIVERGENT', 'POSTED')", name="ck_receiving_reconciliation_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_receiving_reconciliation_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_receiving_reconciliation_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "inbound_fiscal_document_id"],
            ["fiscal.inbound_fiscal_document.company_id", "fiscal.inbound_fiscal_document.id"],
            name="fk_reconciliation_company_inbound",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "goods_receipt_id"],
            ["procurement.goods_receipt.company_id", "procurement.goods_receipt.id"],
            name="fk_reconciliation_company_receipt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_receiving_reconciliation"),
        sa.UniqueConstraint("company_id", "id", name="uq_receiving_reconciliation_company_id"),
        sa.UniqueConstraint(
            "company_id", "inbound_fiscal_document_id", name="uq_reconciliation_inbound"
        ),
        sa.UniqueConstraint("company_id", "goods_receipt_id", name="uq_reconciliation_receipt"),
        schema="fiscal",
    )
    op.create_index(
        "ix_reconciliation_company_status",
        "receiving_reconciliation",
        ["company_id", "status", "reconciled_at"],
        schema="fiscal",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_company_status",
        table_name="receiving_reconciliation",
        schema="fiscal",
    )
    op.drop_table("receiving_reconciliation", schema="fiscal")

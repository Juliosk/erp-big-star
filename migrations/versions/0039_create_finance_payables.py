"""Create M12 payable persistence.

Revision ID: 0039
Revises: 0038
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS finance")
    op.create_table(
        "provisional_entry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.String(40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_tax_id", sa.String(14), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=True),
        sa.Column("void_reason", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "origin IN ('AUTHORIZED_FISCAL_DOCUMENT', 'APPROVED_PURCHASE_ORDER')",
            name="ck_provisional_entry_origin",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CONVERTED', 'VOIDED')",
            name="ck_provisional_entry_status",
        ),
        sa.CheckConstraint("source_version >= 1", name="ck_provisional_entry_source_version"),
        sa.CheckConstraint("amount > 0", name="ck_provisional_entry_amount"),
        sa.CheckConstraint("version >= 1", name="ck_provisional_entry_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_provisional_entry_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provisional_entry"),
        sa.UniqueConstraint("company_id", "id", name="uq_provisional_entry_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "origin",
            "source_id",
            "source_version",
            name="uq_provisional_entry_source",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_provisional_entry_company_status",
        "provisional_entry",
        ["company_id", "status", "id"],
        schema="finance",
    )

    op.create_table(
        "payable",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("document_number", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_tax_id", sa.String(14), nullable=False),
        sa.Column("provisional_entry_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("nominal_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("interest_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("surcharge_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("decision_by", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'SCHEDULED', 'PAID')",
            name="ck_payable_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_payable_version"),
        sa.CheckConstraint(
            "nominal_amount > 0 AND interest_amount >= 0 AND discount_amount >= 0 "
            "AND surcharge_amount >= 0",
            name="ck_payable_amounts",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_payable_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "provisional_entry_id"],
            ["finance.provisional_entry.company_id", "finance.provisional_entry.id"],
            name="fk_payable_company_provisional_entry",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payable"),
        sa.UniqueConstraint("company_id", "id", name="uq_payable_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "document_number",
            "supplier_id",
            name="uq_payable_company_document_supplier",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_payable_company_status",
        "payable",
        ["company_id", "status", "id"],
        schema="finance",
    )

    op.create_table(
        "payable_installment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("payment_reference", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("installment_number >= 1", name="ck_payable_installment_number"),
        sa.CheckConstraint("amount > 0", name="ck_payable_installment_amount"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'SCHEDULED', 'PAID')",
            name="ck_payable_installment_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "payable_id"],
            ["finance.payable.company_id", "finance.payable.id"],
            name="fk_payable_installment_company_payable",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payable_installment"),
        sa.UniqueConstraint("company_id", "id", name="uq_payable_installment_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "payable_id",
            "installment_number",
            name="uq_payable_installment_number",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_payable_installment_company_payable",
        "payable_installment",
        ["company_id", "payable_id", "installment_number"],
        schema="finance",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE finance.provisional_entry "
        "DROP CONSTRAINT IF EXISTS fk_provisional_entry_company_payable"
    )
    op.drop_table("payable_installment", schema="finance")
    op.drop_table("payable", schema="finance")
    op.drop_table("provisional_entry", schema="finance")
    op.execute("DROP SCHEMA IF EXISTS finance")

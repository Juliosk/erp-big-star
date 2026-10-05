"""Create M11 fiscal document persistence. Revision ID: 0035. Revises: 0034."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS fiscal")
    op.create_table(
        "fiscal_document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(2), nullable=False),
        sa.Column("series", sa.Integer(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("issuer_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recipient_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("products_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("access_key", sa.String(44), nullable=True),
        sa.Column("authorization_protocol", sa.String(64), nullable=True),
        sa.Column("rejection_code", sa.String(32), nullable=True),
        sa.Column("rejection_reason", sa.String(1000), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_protocol", sa.String(64), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sefaz_history",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("model IN ('55', '65')", name=op.f("ck_fiscal_document_model")),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ISSUING', 'AUTHORIZED', 'REJECTED', 'DENIED', 'CANCELLED')",
            name=op.f("ck_fiscal_document_status"),
        ),
        sa.CheckConstraint("series >= 1", name=op.f("ck_fiscal_document_series_positive")),
        sa.CheckConstraint("number >= 1", name=op.f("ck_fiscal_document_number_positive")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_fiscal_document_version_positive")),
        sa.CheckConstraint(
            "products_amount >= 0 AND freight_amount >= 0 AND discount_amount >= 0 "
            "AND tax_amount >= 0 AND total_amount >= 0",
            name=op.f("ck_fiscal_document_totals_non_negative"),
        ),
        sa.CheckConstraint(
            "access_key IS NULL OR access_key ~ '^[0-9]{44}$'",
            name=op.f("ck_fiscal_document_access_key_format"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            ondelete="RESTRICT",
            name=op.f("fk_fiscal_document_company_id_company"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_document")),
        sa.UniqueConstraint("company_id", "id", name="uq_fiscal_document_company_id"),
        sa.UniqueConstraint(
            "company_id", "series", "number", name="uq_fiscal_document_company_series_number"
        ),
        sa.UniqueConstraint("access_key", name="uq_fiscal_document_access_key"),
        schema="fiscal",
    )
    op.create_index(
        "ix_fiscal_document_company_status",
        "fiscal_document",
        ["company_id", "status", "id"],
        schema="fiscal",
    )
    op.create_table(
        "fiscal_document_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_document_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("ncm", sa.String(8), nullable=False),
        sa.Column("cfop", sa.String(4), nullable=False),
        sa.Column("unit_of_measure", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("line_number >= 1", name=op.f("ck_fiscal_document_item_line_positive")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_fiscal_document_item_quantity")),
        sa.CheckConstraint(
            "unit_price >= 0 AND freight_amount >= 0 AND discount_amount >= 0 "
            "AND total_amount >= 0",
            name=op.f("ck_fiscal_document_item_amounts"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "fiscal_document_id"],
            ["fiscal.fiscal_document.company_id", "fiscal.fiscal_document.id"],
            name="fk_fiscal_item_company_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_document_item")),
        sa.UniqueConstraint("company_id", "id", name="uq_fiscal_document_item_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "fiscal_document_id",
            "line_number",
            name="uq_fiscal_document_item_line",
        ),
        schema="fiscal",
    )
    op.create_index(
        "ix_fiscal_document_item_document",
        "fiscal_document_item",
        ["company_id", "fiscal_document_id", "line_number"],
        schema="fiscal",
    )


def downgrade() -> None:
    op.drop_table("fiscal_document_item", schema="fiscal")
    op.drop_table("fiscal_document", schema="fiscal")
    op.execute("DROP SCHEMA IF EXISTS fiscal")

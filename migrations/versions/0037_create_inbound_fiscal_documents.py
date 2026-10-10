"""Create inbound fiscal documents and MDE history. Revision ID: 0037. Revises: 0036."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS fiscal")
    op.create_table(
        "inbound_fiscal_document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("access_key", sa.String(44), nullable=False),
        sa.Column("model", sa.String(2), nullable=False),
        sa.Column("series", sa.Integer(), nullable=False),
        sa.Column("number", sa.BigInteger(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_protocol", sa.String(64), nullable=False),
        sa.Column("supplier_tax_id", sa.String(14), nullable=False),
        sa.Column("supplier_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recipient_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("products_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("source_xml", sa.Text(), nullable=False),
        sa.Column("mde_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("model = '55'", name=op.f("ck_inbound_fiscal_document_model")),
        sa.CheckConstraint("series >= 1", name=op.f("ck_inbound_fiscal_document_series")),
        sa.CheckConstraint("number >= 1", name=op.f("ck_inbound_fiscal_document_number")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_inbound_fiscal_document_version")),
        sa.CheckConstraint(
            "products_amount >= 0 AND total_amount >= 0",
            name=op.f("ck_inbound_fiscal_document_totals"),
        ),
        sa.CheckConstraint(
            "access_key ~ '^[0-9]{44}$'", name=op.f("ck_inbound_fiscal_document_access_key")
        ),
        sa.CheckConstraint(
            "mde_status IN ('PENDING', 'ACKNOWLEDGED', 'CONFIRMED', 'UNKNOWN_OPERATION', 'OPERATION_NOT_PERFORMED')",
            name=op.f("ck_inbound_fiscal_document_mde_status"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            ondelete="RESTRICT",
            name=op.f("fk_inbound_fiscal_document_company_id_company"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_fiscal_document")),
        sa.UniqueConstraint("company_id", "id", name="uq_inbound_fiscal_document_company_id"),
        sa.UniqueConstraint("access_key", name="uq_inbound_fiscal_document_access_key"),
        schema="fiscal",
    )
    op.create_index(
        "ix_inbound_fiscal_company_status_date",
        "inbound_fiscal_document",
        ["company_id", "mde_status", "issued_at", "id"],
        schema="fiscal",
    )
    op.create_index(
        "ix_inbound_fiscal_company_supplier",
        "inbound_fiscal_document",
        ["company_id", "supplier_tax_id", "id"],
        schema="fiscal",
    )
    op.create_table(
        "inbound_fiscal_document_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_fiscal_document_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("supplier_code", sa.String(128), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("ncm", sa.String(8), nullable=False),
        sa.Column("cfop", sa.String(4), nullable=False),
        sa.Column("unit_of_measure", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "line_number >= 1 AND quantity > 0", name=op.f("ck_inbound_fiscal_document_item_values")
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND total_amount >= 0",
            name=op.f("ck_inbound_fiscal_document_item_amounts"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "inbound_fiscal_document_id"],
            ["fiscal.inbound_fiscal_document.company_id", "fiscal.inbound_fiscal_document.id"],
            name="fk_inbound_item_company_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_fiscal_document_item")),
        sa.UniqueConstraint("company_id", "id", name="uq_inbound_fiscal_document_item_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            "line_number",
            name="uq_inbound_fiscal_document_item_line",
        ),
        schema="fiscal",
    )
    op.create_index(
        "ix_inbound_fiscal_item_document",
        "inbound_fiscal_document_item",
        ["company_id", "inbound_fiscal_document_id", "line_number"],
        schema="fiscal",
    )
    op.create_table(
        "mde_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_fiscal_document_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(6), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("protocol", sa.String(64), nullable=False),
        sa.Column("status_code", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("event_xml", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('210200', '210210', '210220', '210240')", name=op.f("ck_mde_event_type")
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_mde_event_sequence")),
        sa.ForeignKeyConstraint(
            ["company_id", "inbound_fiscal_document_id"],
            ["fiscal.inbound_fiscal_document.company_id", "fiscal.inbound_fiscal_document.id"],
            name="fk_mde_event_company_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mde_event")),
        sa.UniqueConstraint("company_id", "id", name="uq_mde_event_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            "sequence",
            name="uq_mde_event_document_sequence",
        ),
        sa.UniqueConstraint(
            "company_id",
            "inbound_fiscal_document_id",
            "event_type",
            name="uq_mde_event_document_type",
        ),
        schema="fiscal",
    )
    op.create_index(
        "ix_mde_event_document",
        "mde_event",
        ["company_id", "inbound_fiscal_document_id", "sequence"],
        schema="fiscal",
    )


def downgrade() -> None:
    op.drop_table("mde_event", schema="fiscal")
    op.drop_table("inbound_fiscal_document_item", schema="fiscal")
    op.drop_table("inbound_fiscal_document", schema="fiscal")

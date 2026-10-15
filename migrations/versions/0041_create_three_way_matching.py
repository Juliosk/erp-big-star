"""Create tenant-bound three-way matching persistence.

Revision ID: 0041
Revises: 0040
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matching_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_version", sa.Integer(), nullable=False),
        sa.Column("purchase_order_total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("purchase_order_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "goods_receipts_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "fiscal_documents_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("invoiced_total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("receiving_fiscal_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provisional_entry_id", sa.Uuid(), nullable=False),
        sa.Column("provisional_entry_version", sa.Integer(), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=True),
        sa.Column("payable_version", sa.Integer(), nullable=True),
        sa.Column("obligation_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("financial_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit_price_variance_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("quantity_variance_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("rounding_absolute_limit", sa.Numeric(18, 2), nullable=False),
        sa.Column("tolerance_policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("report_status", sa.String(24), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_by", sa.Uuid(), nullable=True),
        sa.Column("decision_workflow_instance_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(500), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'MATCHED', 'DISCREPANCY_DETECTED', "
            "'OVERRIDDEN', 'REJECTED')",
            name="ck_matching_session_status",
        ),
        sa.CheckConstraint(
            "report_status IS NULL OR report_status IN "
            "('MATCHED', 'TOLERANCE_EXCEEDED', 'QUANTITY_MISMATCH', 'PRICE_MISMATCH')",
            name="ck_matching_session_report_status",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_matching_session_currency"),
        sa.CheckConstraint(
            "purchase_order_version >= 1 AND provisional_entry_version >= 1 "
            "AND tolerance_policy_version >= 1 AND version >= 1",
            name="ck_matching_session_versions",
        ),
        sa.CheckConstraint(
            "(payable_id IS NULL AND payable_version IS NULL) OR "
            "(payable_id IS NOT NULL AND payable_version >= 1)",
            name="ck_matching_session_payable_reference",
        ),
        sa.CheckConstraint(
            "purchase_order_total_amount > 0 AND invoiced_total_amount > 0 "
            "AND obligation_amount > 0",
            name="ck_matching_session_amounts",
        ),
        sa.CheckConstraint(
            "unit_price_variance_percentage BETWEEN 0 AND 100 "
            "AND quantity_variance_percentage BETWEEN 0 AND 100 "
            "AND rounding_absolute_limit BETWEEN 0 AND 1",
            name="ck_matching_session_tolerances",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_matching_session_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_matching_session_company_supplier",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["procurement.purchase_order.company_id", "procurement.purchase_order.id"],
            name="fk_matching_session_company_purchase_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "provisional_entry_id"],
            ["finance.provisional_entry.company_id", "finance.provisional_entry.id"],
            name="fk_matching_session_company_provisional_entry",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "payable_id"],
            ["finance.payable.company_id", "finance.payable.id"],
            name="fk_matching_session_company_payable",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matching_session"),
        sa.UniqueConstraint("company_id", "id", name="uq_matching_session_company_id"),
        schema="procurement",
    )
    op.create_index(
        "ix_matching_session_company_status",
        "matching_session",
        ["company_id", "status", "id"],
        schema="procurement",
    )
    op.create_index(
        "ix_matching_session_company_purchase_order",
        "matching_session",
        ["company_id", "purchase_order_id", "id"],
        schema="procurement",
    )

    op.create_table(
        "matching_session_item",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("matching_session_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("match_key", sa.String(64), nullable=False),
        sa.Column("purchase_order_item_id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_item_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_document_item_id", sa.Uuid(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("invoiced_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("ordered_unit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("invoiced_unit_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=True),
        sa.Column("quantity_delta", sa.Numeric(18, 6), nullable=True),
        sa.Column("unit_price_delta", sa.Numeric(18, 6), nullable=True),
        sa.Column("allowed_quantity_delta", sa.Numeric(18, 6), nullable=True),
        sa.Column("allowed_unit_price_delta", sa.Numeric(18, 6), nullable=True),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("match_key ~ '^[A-Z0-9][A-Z0-9._/-]*$'", name="ck_matching_item_key"),
        sa.CheckConstraint("line_number >= 1", name="ck_matching_item_line_number"),
        sa.CheckConstraint(
            "ordered_quantity > 0 AND received_quantity >= 0 AND invoiced_quantity > 0",
            name="ck_matching_item_quantities",
        ),
        sa.CheckConstraint(
            "ordered_unit_price >= 0 AND invoiced_unit_price >= 0",
            name="ck_matching_item_prices",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_matching_item_currency"),
        sa.CheckConstraint(
            "result_status IS NULL OR result_status IN "
            "('MATCHED', 'TOLERANCE_EXCEEDED', 'QUANTITY_MISMATCH', 'PRICE_MISMATCH')",
            name="ck_matching_item_result_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_matching_item_company_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_item_id"],
            ["procurement.purchase_order_item.company_id", "procurement.purchase_order_item.id"],
            name="fk_matching_item_company_purchase_order_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "goods_receipt_item_id"],
            ["procurement.receipt_item.company_id", "procurement.receipt_item.id"],
            name="fk_matching_item_company_goods_receipt_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "fiscal_document_item_id"],
            [
                "fiscal.inbound_fiscal_document_item.company_id",
                "fiscal.inbound_fiscal_document_item.id",
            ],
            name="fk_matching_item_company_fiscal_document_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "matching_session_id",
            "match_key",
            name="pk_matching_session_item",
        ),
        sa.UniqueConstraint(
            "company_id",
            "matching_session_id",
            "line_number",
            name="uq_matching_item_session_line_number",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_matching_item_company_session",
        "matching_session_item",
        ["company_id", "matching_session_id", "line_number"],
        schema="procurement",
    )

    op.create_table(
        "matching_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("matching_session_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("aggregate_version >= 1", name="ck_matching_audit_version"),
        sa.CheckConstraint(
            "to_status IN ('PENDING', 'RUNNING', 'MATCHED', 'DISCREPANCY_DETECTED', "
            "'OVERRIDDEN', 'REJECTED')",
            name="ck_matching_audit_to_status",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('PENDING', 'RUNNING', 'MATCHED', 'DISCREPANCY_DETECTED', 'OVERRIDDEN', 'REJECTED')",
            name="ck_matching_audit_from_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_matching_audit_company_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matching_audit_log"),
        sa.UniqueConstraint(
            "company_id",
            "matching_session_id",
            "aggregate_version",
            name="uq_matching_audit_session_version",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_matching_audit_company_session",
        "matching_audit_log",
        ["company_id", "matching_session_id", "aggregate_version"],
        schema="procurement",
    )
    op.execute(
        """
        CREATE FUNCTION procurement.reject_matching_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('erp.allow_matching_audit_cleanup', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'matching audit log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"""
            CREATE TRIGGER trg_matching_audit_append_only_{operation.lower()}
            BEFORE {operation} ON procurement.matching_audit_log
            FOR EACH ROW EXECUTE FUNCTION procurement.reject_matching_audit_mutation();
            """
        )


def downgrade() -> None:
    for operation in ("DELETE", "UPDATE"):
        op.execute(
            "DROP TRIGGER IF EXISTS "
            f"trg_matching_audit_append_only_{operation.lower()} "
            "ON procurement.matching_audit_log"
        )
    op.drop_table("matching_audit_log", schema="procurement")
    op.drop_table("matching_session_item", schema="procurement")
    op.drop_table("matching_session", schema="procurement")
    op.execute("DROP FUNCTION IF EXISTS procurement.reject_matching_audit_mutation()")

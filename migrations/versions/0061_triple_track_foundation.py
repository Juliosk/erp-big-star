"""Persist the fiscal, procurement and treasury triple-track foundations.

Revision ID: 0061
Revises: 0060
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_tax_rules()
    _create_request_for_quotation()
    _create_payment_requests()


def downgrade() -> None:
    op.drop_table("payment_request_item", schema="finance")
    op.drop_table("payment_request", schema="finance")
    op.drop_table("rfq_supplier_quote_line", schema="procurement")
    op.drop_table("rfq_supplier", schema="procurement")
    op.drop_table("rfq_item", schema="procurement")
    op.drop_table("request_for_quotation", schema="procurement")
    op.drop_table("tax_rule", schema="fiscal")


def _create_tax_rules() -> None:
    op.create_table(
        "tax_rule",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("version_code", sa.String(32), nullable=False),
        sa.Column("flow", sa.String(16), nullable=False),
        sa.Column("ncm", sa.String(8), nullable=False),
        sa.Column("cfop", sa.String(4), nullable=False),
        sa.Column("origin_country_code", sa.String(2), nullable=False),
        sa.Column("origin_state_code", sa.String(2), nullable=True),
        sa.Column("origin_municipality_code", sa.String(7), nullable=True),
        sa.Column("destination_country_code", sa.String(2), nullable=False),
        sa.Column("destination_state_code", sa.String(2), nullable=True),
        sa.Column("destination_municipality_code", sa.String(7), nullable=True),
        sa.Column("icms_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("pis_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("cofins_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("ipi_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("activated_by", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("flow IN ('INBOUND', 'OUTBOUND')", name="ck_tax_rule_flow"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name="ck_tax_rule_status",
        ),
        sa.CheckConstraint("ncm ~ '^[0-9]{8}$'", name="ck_tax_rule_ncm"),
        sa.CheckConstraint("cfop ~ '^[0-9]{4}$'", name="ck_tax_rule_cfop"),
        sa.CheckConstraint(
            "origin_country_code ~ '^[A-Z]{2}$' AND destination_country_code ~ '^[A-Z]{2}$'",
            name="ck_tax_rule_countries",
        ),
        sa.CheckConstraint(
            "origin_municipality_code IS NULL OR "
            "(origin_state_code IS NOT NULL AND origin_municipality_code ~ '^[0-9]{7}$')",
            name="ck_tax_rule_origin_jurisdiction",
        ),
        sa.CheckConstraint(
            "destination_municipality_code IS NULL OR "
            "(destination_state_code IS NOT NULL "
            "AND destination_municipality_code ~ '^[0-9]{7}$')",
            name="ck_tax_rule_destination_jurisdiction",
        ),
        sa.CheckConstraint(
            "icms_rate BETWEEN 0 AND 1 AND pis_rate BETWEEN 0 AND 1 AND "
            "cofins_rate BETWEEN 0 AND 1 AND ipi_rate BETWEEN 0 AND 1",
            name="ck_tax_rule_rates",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_tax_rule_effective_period",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND activated_by IS NULL AND activated_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'ACTIVE' AND activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'RETIRED' AND activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND retired_at IS NOT NULL AND retired_at >= activated_at)",
            name="ck_tax_rule_lifecycle_evidence",
        ),
        sa.CheckConstraint("version >= 1", name="ck_tax_rule_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_tax_rule_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_rule"),
        sa.UniqueConstraint("company_id", "id", name="uq_tax_rule_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "code",
            "version_code",
            name="uq_tax_rule_company_code_version",
        ),
        schema="fiscal",
    )
    op.create_index(
        "ix_tax_rule_company_status_effective",
        "tax_rule",
        ["company_id", "status", "effective_from", "effective_until", "id"],
        schema="fiscal",
    )
    op.create_index(
        "ix_tax_rule_resolution",
        "tax_rule",
        ["company_id", "flow", "ncm", "cfop", "status"],
        schema="fiscal",
    )


def _create_request_for_quotation() -> None:
    op.create_table(
        "request_for_quotation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("response_deadline", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awarded_quote_id", sa.Uuid(), nullable=True),
        sa.Column("awarded_supplier_id", sa.Uuid(), nullable=True),
        sa.Column("awarded_by", sa.Uuid(), nullable=True),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'CLOSED', 'AWARDED', 'CANCELLED')",
            name="ck_request_for_quotation_status",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND opened_at IS NULL AND closed_at IS NULL) OR "
            "(status = 'OPEN' AND opened_at IS NOT NULL AND closed_at IS NULL) OR "
            "(status IN ('CLOSED', 'AWARDED') AND opened_at IS NOT NULL "
            "AND closed_at IS NOT NULL) OR status = 'CANCELLED'",
            name="ck_request_for_quotation_timeline",
        ),
        sa.CheckConstraint(
            "(status = 'AWARDED') = (awarded_quote_id IS NOT NULL "
            "AND awarded_supplier_id IS NOT NULL AND awarded_by IS NOT NULL "
            "AND awarded_at IS NOT NULL)",
            name="ck_request_for_quotation_award",
        ),
        sa.CheckConstraint(
            "(status = 'CANCELLED') = (cancellation_reason IS NOT NULL)",
            name="ck_request_for_quotation_cancellation",
        ),
        sa.CheckConstraint("version >= 1", name="ck_request_for_quotation_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_request_for_quotation_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_request_for_quotation"),
        sa.UniqueConstraint("company_id", "id", name="uq_request_for_quotation_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_request_for_quotation_code"),
        schema="procurement",
    )
    op.create_index(
        "ix_request_for_quotation_queue",
        "request_for_quotation",
        ["company_id", "status", "response_deadline", "id"],
        schema="procurement",
    )

    op.create_table(
        "rfq_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("rfq_id", sa.Uuid(), nullable=False),
        sa.Column("item_sequence", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("uom", sa.String(8), nullable=False),
        sa.Column("required_on", sa.Date(), nullable=False),
        sa.Column("specification", sa.String(500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "rfq_id"],
            [
                "procurement.request_for_quotation.company_id",
                "procurement.request_for_quotation.id",
            ],
            name="fk_rfq_item_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_rfq_item_product",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_rfq_item_quantity"),
        sa.CheckConstraint("item_sequence >= 1", name="ck_rfq_item_sequence"),
        sa.PrimaryKeyConstraint("id", name="pk_rfq_item"),
        sa.UniqueConstraint("company_id", "rfq_id", "id", name="uq_rfq_item_scope"),
        sa.UniqueConstraint(
            "company_id",
            "rfq_id",
            "product_id",
            name="uq_rfq_item_product",
        ),
        sa.UniqueConstraint(
            "company_id",
            "rfq_id",
            "item_sequence",
            name="uq_rfq_item_sequence",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_rfq_item_request",
        "rfq_item",
        ["company_id", "rfq_id", "required_on", "id"],
        schema="procurement",
    )

    op.create_table(
        "rfq_supplier",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("rfq_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_sequence", sa.Integer(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=True),
        sa.Column("quote_sequence", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "rfq_id"],
            [
                "procurement.request_for_quotation.company_id",
                "procurement.request_for_quotation.id",
            ],
            name="fk_rfq_supplier_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_rfq_supplier_supplier",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(quote_id IS NULL AND quote_sequence IS NULL AND currency IS NULL "
            "AND submitted_at IS NULL "
            "AND valid_until IS NULL AND freight_amount IS NULL) OR "
            "(quote_id IS NOT NULL AND quote_sequence >= 1 AND currency IS NOT NULL "
            "AND submitted_at IS NOT NULL AND valid_until IS NOT NULL "
            "AND freight_amount >= 0)",
            name="ck_rfq_supplier_quote_snapshot",
        ),
        sa.CheckConstraint(
            "invitation_sequence >= 1",
            name="ck_rfq_supplier_invitation_sequence",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "rfq_id",
            "supplier_id",
            name="pk_rfq_supplier",
        ),
        sa.UniqueConstraint(
            "company_id",
            "rfq_id",
            "quote_id",
            name="uq_rfq_supplier_quote",
        ),
        sa.UniqueConstraint(
            "company_id",
            "rfq_id",
            "invitation_sequence",
            name="uq_rfq_supplier_invitation_sequence",
        ),
        sa.UniqueConstraint(
            "company_id",
            "rfq_id",
            "quote_sequence",
            name="uq_rfq_supplier_quote_sequence",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_rfq_supplier_request",
        "rfq_supplier",
        ["company_id", "rfq_id", "supplier_id"],
        schema="procurement",
    )

    op.create_table(
        "rfq_supplier_quote_line",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("rfq_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("rfq_item_id", sa.Uuid(), nullable=False),
        sa.Column("offered_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "rfq_id", "supplier_id"],
            [
                "procurement.rfq_supplier.company_id",
                "procurement.rfq_supplier.rfq_id",
                "procurement.rfq_supplier.supplier_id",
            ],
            name="fk_rfq_quote_line_supplier",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "rfq_id", "rfq_item_id"],
            [
                "procurement.rfq_item.company_id",
                "procurement.rfq_item.rfq_id",
                "procurement.rfq_item.id",
            ],
            name="fk_rfq_quote_line_item",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "offered_quantity > 0 AND unit_price > 0 AND lead_time_days >= 0",
            name="ck_rfq_quote_line_values",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "rfq_id",
            "supplier_id",
            "rfq_item_id",
            name="pk_rfq_supplier_quote_line",
        ),
        schema="procurement",
    )


def _create_payment_requests() -> None:
    op.create_table(
        "payment_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("treasury_account_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("transition_reason", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', "
            "'CANCELLED', 'BATCHED')",
            name="ck_payment_request_status",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payment_request_currency"),
        sa.CheckConstraint("total_amount > 0", name="ck_payment_request_total"),
        sa.CheckConstraint("version >= 1", name="ck_payment_request_version"),
        sa.CheckConstraint(
            "status NOT IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'BATCHED') "
            "OR workflow_instance_id IS NOT NULL",
            name="ck_payment_request_workflow",
        ),
        sa.CheckConstraint(
            "status NOT IN ('APPROVED', 'REJECTED', 'BATCHED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_payment_request_decision",
        ),
        sa.CheckConstraint(
            "(status = 'BATCHED') = (batch_id IS NOT NULL)",
            name="ck_payment_request_batch",
        ),
        sa.CheckConstraint(
            "status NOT IN ('REJECTED', 'CANCELLED') OR transition_reason IS NOT NULL",
            name="ck_payment_request_reason",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_payment_request_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_payment_request_batch",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_request"),
        sa.UniqueConstraint("company_id", "id", name="uq_payment_request_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_payment_request_code"),
        schema="finance",
    )
    op.create_index(
        "ix_payment_request_queue",
        "payment_request",
        ["company_id", "status", "scheduled_on", "id"],
        schema="finance",
    )

    op.create_table(
        "payment_request_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("payment_request_id", sa.Uuid(), nullable=False),
        sa.Column("item_sequence", sa.Integer(), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("installment_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("matching_session_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("beneficiary_bank_code", sa.String(3), nullable=False),
        sa.Column("beneficiary_branch_number", sa.String(5), nullable=False),
        sa.Column("beneficiary_account_number", sa.String(20), nullable=False),
        sa.Column("beneficiary_account_digit", sa.String(2), nullable=False),
        sa.Column("beneficiary_account_type", sa.String(16), nullable=False),
        sa.Column("beneficiary_holder_name", sa.String(120), nullable=False),
        sa.Column("beneficiary_holder_tax_id", sa.String(14), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "payment_request_id"],
            ["finance.payment_request.company_id", "finance.payment_request.id"],
            name="fk_payment_request_item_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "payable_id", "installment_id"],
            [
                "finance.payable_installment.company_id",
                "finance.payable_installment.payable_id",
                "finance.payable_installment.id",
            ],
            name="fk_payment_request_item_installment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_payment_request_item_matching",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_payment_request_item_supplier",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_request_item_amount"),
        sa.CheckConstraint(
            "item_sequence >= 1",
            name="ck_payment_request_item_sequence",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_payment_request_item_currency",
        ),
        sa.CheckConstraint(
            "beneficiary_account_type IN ('CHECKING', 'SAVINGS', 'PAYMENT')",
            name="ck_payment_request_item_account_type",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_request_item"),
        sa.UniqueConstraint("company_id", "id", name="uq_payment_request_item_scope"),
        sa.UniqueConstraint(
            "company_id",
            "payment_request_id",
            "installment_id",
            name="uq_payment_request_item_installment",
        ),
        sa.UniqueConstraint(
            "company_id",
            "payment_request_id",
            "item_sequence",
            name="uq_payment_request_item_sequence",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_payment_request_item_request",
        "payment_request_item",
        ["company_id", "payment_request_id", "due_date", "id"],
        schema="finance",
    )

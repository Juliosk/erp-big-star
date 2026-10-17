"""Create M12 treasury payment-batch persistence.

Revision ID: 0043
Revises: 0042
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH_STATUSES = (
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "RELEASED",
    "SUBMITTED",
    "CONFIRMED",
    "REJECTED",
    "CANCELLED",
)


def _status_sql(column: str) -> str:
    values = ", ".join(f"'{value}'" for value in _BATCH_STATUSES)
    return f"{column} IN ({values})"


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_payable_installment_company_payable_id",
        "payable_installment",
        ["company_id", "payable_id", "id"],
        schema="finance",
    )
    op.create_table(
        "payment_batch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("treasury_account_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("remittance_format", sa.String(16), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("released_by", sa.Uuid(), nullable=True),
        sa.Column("submission_protocol", sa.String(120), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transition_reason", sa.String(500), nullable=True),
        sa.Column("bank_confirmation_protocol", sa.String(120), nullable=True),
        sa.Column("bank_confirmation_status", sa.String(40), nullable=True),
        sa.Column("bank_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bank_confirmed_amount", sa.Numeric(18, 2), nullable=True),
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
        sa.CheckConstraint(_status_sql("status"), name="ck_payment_batch_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payment_batch_currency"),
        sa.CheckConstraint("total_amount > 0", name="ck_payment_batch_total_amount"),
        sa.CheckConstraint("version >= 1", name="ck_payment_batch_version"),
        sa.CheckConstraint(
            "remittance_format IN ('CNAB_240', 'CNAB_400', 'PIX_API')",
            name="ck_payment_batch_remittance_format",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('DRY_RUN', 'HOMOLOGATION', 'PRODUCTION')",
            name="ck_payment_batch_execution_mode",
        ),
        sa.CheckConstraint(
            "status NOT IN ('APPROVED', 'RELEASED', 'SUBMITTED', 'CONFIRMED') "
            "OR approved_by IS NOT NULL",
            name="ck_payment_batch_approval_evidence",
        ),
        sa.CheckConstraint(
            "status NOT IN ('RELEASED', 'SUBMITTED', 'CONFIRMED') OR released_by IS NOT NULL",
            name="ck_payment_batch_release_evidence",
        ),
        sa.CheckConstraint(
            "status NOT IN ('SUBMITTED', 'CONFIRMED') OR "
            "(submission_protocol IS NOT NULL AND submitted_at IS NOT NULL)",
            name="ck_payment_batch_submission_evidence",
        ),
        sa.CheckConstraint(
            "(status = 'CONFIRMED' AND bank_confirmation_protocol IS NOT NULL "
            "AND bank_confirmation_status IS NOT NULL AND bank_confirmed_at IS NOT NULL "
            "AND bank_confirmed_amount = total_amount) OR "
            "(status <> 'CONFIRMED' AND bank_confirmation_protocol IS NULL "
            "AND bank_confirmation_status IS NULL AND bank_confirmed_at IS NULL "
            "AND bank_confirmed_amount IS NULL)",
            name="ck_payment_batch_bank_confirmation",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_payment_batch_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_batch"),
        sa.UniqueConstraint("company_id", "id", name="uq_payment_batch_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_payment_batch_company_code"),
        schema="finance",
    )
    op.create_index(
        "ix_payment_batch_company_status",
        "payment_batch",
        ["company_id", "status", "scheduled_date", "id"],
        schema="finance",
    )

    op.create_table(
        "payment_batch_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("payment_batch_id", sa.Uuid(), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("installment_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("matching_session_id", sa.Uuid(), nullable=False),
        sa.Column("payable_created_by", sa.Uuid(), nullable=False),
        sa.Column("payable_approved_by", sa.Uuid(), nullable=False),
        sa.Column("beneficiary_bank_code", sa.String(3), nullable=False),
        sa.Column("beneficiary_branch_number", sa.String(5), nullable=False),
        sa.Column("beneficiary_account_number", sa.String(20), nullable=False),
        sa.Column("beneficiary_account_digit", sa.String(2), nullable=False),
        sa.Column("beneficiary_account_type", sa.String(16), nullable=False),
        sa.Column("beneficiary_holder_name", sa.String(120), nullable=False),
        sa.Column("beneficiary_holder_tax_id", sa.String(14), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_batch_item_amount"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payment_batch_item_currency"),
        sa.CheckConstraint(
            "beneficiary_account_type IN ('CHECKING', 'SAVINGS', 'PAYMENT')",
            name="ck_payment_batch_item_account_type",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "payment_batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_payment_batch_item_company_batch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "payable_id", "installment_id"],
            [
                "finance.payable_installment.company_id",
                "finance.payable_installment.payable_id",
                "finance.payable_installment.id",
            ],
            name="fk_payment_batch_item_company_installment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_payment_batch_item_company_matching",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_payment_batch_item_company_supplier",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_batch_item"),
        sa.UniqueConstraint("company_id", "id", name="uq_payment_batch_item_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "payment_batch_id",
            "installment_id",
            name="uq_payment_batch_item_batch_installment",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_payment_batch_item_company_batch",
        "payment_batch_item",
        ["company_id", "payment_batch_id", "due_date", "id"],
        schema="finance",
    )

    op.create_table(
        "batch_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("payment_batch_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(_status_sql("to_status"), name="ck_batch_audit_to_status"),
        sa.CheckConstraint(
            f"from_status IS NULL OR {_status_sql('from_status')}",
            name="ck_batch_audit_from_status",
        ),
        sa.CheckConstraint("aggregate_version >= 1", name="ck_batch_audit_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "payment_batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_batch_audit_company_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_batch_audit_log"),
        sa.UniqueConstraint(
            "company_id",
            "payment_batch_id",
            "aggregate_version",
            name="uq_batch_audit_batch_version",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_batch_audit_company_batch",
        "batch_audit_log",
        ["company_id", "payment_batch_id", "aggregate_version"],
        schema="finance",
    )
    op.execute(
        """
        CREATE FUNCTION finance.reject_batch_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('erp.allow_treasury_audit_cleanup', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'treasury batch audit log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"""
            CREATE TRIGGER trg_batch_audit_append_only_{operation.lower()}
            BEFORE {operation} ON finance.batch_audit_log
            FOR EACH ROW EXECUTE FUNCTION finance.reject_batch_audit_mutation();
            """
        )


def downgrade() -> None:
    for operation in ("DELETE", "UPDATE"):
        op.execute(
            "DROP TRIGGER IF EXISTS "
            f"trg_batch_audit_append_only_{operation.lower()} "
            "ON finance.batch_audit_log"
        )
    op.drop_table("batch_audit_log", schema="finance")
    op.drop_table("payment_batch_item", schema="finance")
    op.drop_table("payment_batch", schema="finance")
    op.execute("DROP FUNCTION IF EXISTS finance.reject_batch_audit_mutation()")
    op.drop_constraint(
        "uq_payable_installment_company_payable_id",
        "payable_installment",
        schema="finance",
        type_="unique",
    )

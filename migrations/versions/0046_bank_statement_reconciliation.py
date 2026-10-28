"""Persist tenant-bound bank statements and reconciliation evidence.

Revision ID: 0046
Revises: 0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_statement",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("bank_code", sa.String(20), nullable=False),
        sa.Column("account_reference", sa.String(80), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("opening_balance", sa.Numeric(19, 4), nullable=True),
        sa.Column("closing_balance", sa.Numeric(19, 4), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.CheckConstraint("period_start <= period_end", name="ck_bank_statement_period"),
        sa.CheckConstraint("source IN ('OFX', 'CSV')", name="ck_bank_statement_source"),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name="ck_bank_statement_source_hash",
        ),
        sa.CheckConstraint("version >= 1", name="ck_bank_statement_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_bank_statement_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bank_statement"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_bank_statement_company_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "bank_account_id",
            "source_hash",
            name="uq_bank_statement_company_account_hash",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_bank_statement_company_account_period",
        "bank_statement",
        ["company_id", "bank_account_id", "period_start", "period_end", "id"],
        schema="finance",
    )
    op.create_index(
        "ix_bank_statement_company_hash",
        "bank_statement",
        ["company_id", "source_hash"],
        schema="finance",
    )

    op.create_table(
        "bank_movement",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("bank_statement_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("booked_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("document_number", sa.String(120), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("matched_reference_id", sa.Uuid(), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_score", sa.Numeric(5, 4), nullable=True),
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
        sa.CheckConstraint("amount > 0", name="ck_bank_movement_amount"),
        sa.CheckConstraint("sequence_number >= 1", name="ck_bank_movement_sequence"),
        sa.CheckConstraint(
            "direction IN ('CREDIT', 'DEBIT')",
            name="ck_bank_movement_direction",
        ),
        sa.CheckConstraint(
            "kind IN ('TRANSFER', 'PAYMENT', 'RECEIPT', 'BANK_FEE', "
            "'INTEREST', 'TAX', 'OTHER')",
            name="ck_bank_movement_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RECONCILED')",
            name="ck_bank_movement_status",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND matched_reference_id IS NULL AND "
            "reconciled_at IS NULL AND match_score IS NULL) OR "
            "(status = 'RECONCILED' AND matched_reference_id IS NOT NULL AND "
            "reconciled_at IS NOT NULL AND match_score BETWEEN 0 AND 1)",
            name="ck_bank_movement_reconciliation_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "bank_statement_id"],
            ["finance.bank_statement.company_id", "finance.bank_statement.id"],
            name="fk_bank_movement_company_statement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bank_movement"),
        sa.UniqueConstraint(
            "company_id",
            "bank_statement_id",
            "id",
            name="uq_bank_movement_company_statement_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "bank_statement_id",
            "external_id",
            name="uq_bank_movement_statement_external_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "bank_statement_id",
            "sequence_number",
            name="uq_bank_movement_statement_sequence",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_bank_movement_company_account_date",
        "bank_movement",
        ["company_id", "bank_account_id", "booked_on", "status", "id"],
        schema="finance",
    )

    op.create_table(
        "statement_import_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("bank_statement_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("original_file_name", sa.String(255), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("movement_count", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("source IN ('OFX', 'CSV')", name="ck_statement_import_source"),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name="ck_statement_import_hash",
        ),
        sa.CheckConstraint("file_size_bytes >= 0", name="ck_statement_import_size"),
        sa.CheckConstraint("movement_count > 0", name="ck_statement_import_count"),
        sa.ForeignKeyConstraint(
            ["company_id", "bank_statement_id"],
            ["finance.bank_statement.company_id", "finance.bank_statement.id"],
            name="fk_statement_import_company_statement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_statement_import_audit"),
        sa.UniqueConstraint(
            "company_id",
            "bank_statement_id",
            name="uq_statement_import_company_statement",
        ),
        schema="finance",
    )

    op.create_table(
        "conciliation_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("bank_statement_id", sa.Uuid(), nullable=False),
        sa.Column("bank_movement_id", sa.Uuid(), nullable=False),
        sa.Column("matched_reference_id", sa.Uuid(), nullable=False),
        sa.Column("match_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "match_score BETWEEN 0 AND 1",
            name="ck_conciliation_record_score",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "bank_statement_id", "bank_movement_id"],
            [
                "finance.bank_movement.company_id",
                "finance.bank_movement.bank_statement_id",
                "finance.bank_movement.id",
            ],
            name="fk_conciliation_record_company_movement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conciliation_record"),
        sa.UniqueConstraint(
            "company_id",
            "bank_movement_id",
            name="uq_conciliation_record_company_movement",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_conciliation_record_company_reference",
        "conciliation_record",
        ["company_id", "matched_reference_id", "reconciled_at"],
        schema="finance",
    )

    op.execute(
        """
        CREATE FUNCTION finance.reject_bank_reconciliation_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF current_setting('erp.allow_bank_reconciliation_audit_cleanup', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'bank reconciliation audit is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("statement_import_audit", "conciliation_record"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON finance.{table}
            FOR EACH ROW EXECUTE FUNCTION finance.reject_bank_reconciliation_audit_mutation();
            """
        )


def downgrade() -> None:
    for table in ("conciliation_record", "statement_import_audit"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON finance.{table}")
    op.execute("DROP FUNCTION IF EXISTS finance.reject_bank_reconciliation_audit_mutation()")
    op.drop_table("conciliation_record", schema="finance")
    op.drop_table("statement_import_audit", schema="finance")
    op.drop_table("bank_movement", schema="finance")
    op.drop_table("bank_statement", schema="finance")

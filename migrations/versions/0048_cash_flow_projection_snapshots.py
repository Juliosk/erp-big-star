"""Persist immutable Cash Flow scenarios, snapshots and audit evidence.

Revision ID: 0048
Revises: 0047
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cash_flow_scenario_definition",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("receivable_delay_days", sa.Integer(), nullable=False),
        sa.Column("cost_variation_rate", sa.Numeric(9, 4), nullable=False),
        sa.Column("business_day_convention", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "receivable_delay_days BETWEEN 0 AND 365",
            name="ck_cash_flow_scenario_delay",
        ),
        sa.CheckConstraint(
            "cost_variation_rate BETWEEN -1 AND 10",
            name="ck_cash_flow_scenario_cost_rate",
        ),
        sa.CheckConstraint(
            "business_day_convention IN ('FOLLOWING', 'PRECEDING', 'UNADJUSTED')",
            name="ck_cash_flow_scenario_business_day",
        ),
        sa.CheckConstraint("version >= 1", name="ck_cash_flow_scenario_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_cash_flow_scenario_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cash_flow_scenario_definition"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_cash_flow_scenario_company_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "name",
            name="uq_cash_flow_scenario_company_name",
        ),
        schema="finance",
    )

    op.create_table(
        "cash_flow_projection_snapshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_start", sa.Date(), nullable=False),
        sa.Column("horizon_end", sa.Date(), nullable=False),
        sa.Column("granularity", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("opening_balance", sa.Numeric(19, 2), nullable=False),
        sa.Column("minimum_reserve", sa.Numeric(19, 2), nullable=False),
        sa.Column("operational_closing_balance", sa.Numeric(19, 2), nullable=False),
        sa.Column("scenario_closing_balance", sa.Numeric(19, 2), nullable=False),
        sa.Column("liquidity_state", sa.String(16), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_cash_flow_snapshot_version"),
        sa.CheckConstraint(
            "as_of = horizon_start AND horizon_start <= horizon_end",
            name="ck_cash_flow_snapshot_horizon",
        ),
        sa.CheckConstraint(
            "granularity IN ('DAILY', 'WEEKLY', 'MONTHLY')",
            name="ck_cash_flow_snapshot_granularity",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_cash_flow_snapshot_currency",
        ),
        sa.CheckConstraint(
            "minimum_reserve >= 0",
            name="ck_cash_flow_snapshot_reserve",
        ),
        sa.CheckConstraint(
            "liquidity_state IN ('HEALTHY', 'ATTENTION', 'CRITICAL', 'INCOMPLETE')",
            name="ck_cash_flow_snapshot_liquidity",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "scenario_id"],
            [
                "finance.cash_flow_scenario_definition.company_id",
                "finance.cash_flow_scenario_definition.id",
            ],
            name="fk_cash_flow_snapshot_company_scenario",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            "version",
            name="pk_cash_flow_projection_snapshot",
        ),
        sa.UniqueConstraint(
            "company_id",
            "id",
            "version",
            name="uq_cash_flow_snapshot_company_id_version",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_snapshot_company_as_of_horizon",
        "cash_flow_projection_snapshot",
        ["company_id", "as_of", "horizon_end", "id", "version"],
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_snapshot_company_calculated",
        "cash_flow_projection_snapshot",
        ["company_id", "calculated_at", "id", "version"],
        schema="finance",
    )

    op.create_table(
        "cash_flow_audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "action IN ('CREATED', 'RECALCULATED')",
            name="ck_cash_flow_audit_action",
        ),
        sa.CheckConstraint(
            "projection_version >= 1",
            name="ck_cash_flow_audit_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "projection_id", "projection_version"],
            [
                "finance.cash_flow_projection_snapshot.company_id",
                "finance.cash_flow_projection_snapshot.id",
                "finance.cash_flow_projection_snapshot.version",
            ],
            name="fk_cash_flow_audit_company_snapshot",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cash_flow_audit_log"),
        sa.UniqueConstraint(
            "company_id",
            "projection_id",
            "projection_version",
            name="uq_cash_flow_audit_company_projection_version",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_audit_company_projection",
        "cash_flow_audit_log",
        ["company_id", "projection_id", "projection_version"],
        schema="finance",
    )

    op.execute(
        """
        CREATE FUNCTION finance.reject_cash_flow_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF current_setting('erp.allow_cash_flow_cleanup', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'cash flow snapshots are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in (
        "cash_flow_scenario_definition",
        "cash_flow_projection_snapshot",
        "cash_flow_audit_log",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON finance.{table}
            FOR EACH ROW EXECUTE FUNCTION finance.reject_cash_flow_snapshot_mutation();
            """
        )


def downgrade() -> None:
    for table in (
        "cash_flow_audit_log",
        "cash_flow_projection_snapshot",
        "cash_flow_scenario_definition",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON finance.{table}")
    op.execute("DROP FUNCTION IF EXISTS finance.reject_cash_flow_snapshot_mutation()")
    op.drop_table("cash_flow_audit_log", schema="finance")
    op.drop_table("cash_flow_projection_snapshot", schema="finance")
    op.drop_table("cash_flow_scenario_definition", schema="finance")

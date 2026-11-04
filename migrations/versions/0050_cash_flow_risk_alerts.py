"""Persist Cash Flow rupture, concentration and sensitivity alerts.

Revision ID: 0050
Revises: 0049
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cash_flow_alert",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("alert_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("subject_key", sa.String(300), nullable=False),
        sa.Column("breach_on", sa.Date(), nullable=True),
        sa.Column("actual_value", sa.Numeric(19, 4), nullable=False),
        sa.Column("threshold_value", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("projection_version >= 1", name="ck_cash_flow_alert_version"),
        sa.CheckConstraint(
            "source IN ('PROJECTION', 'SCENARIO')",
            name="ck_cash_flow_alert_source",
        ),
        sa.CheckConstraint(
            "alert_type IN ('CASH_RUPTURE', 'SAFETY_THRESHOLD', "
            "'DATE_CONCENTRATION', 'CATEGORY_CONCENTRATION', "
            "'EXPOSURE_CONCENTRATION', 'DAILY_OUTLIER', 'SCENARIO_SENSITIVITY')",
            name="ck_cash_flow_alert_type",
        ),
        sa.CheckConstraint(
            "severity IN ('WARNING', 'CRITICAL')",
            name="ck_cash_flow_alert_severity",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_cash_flow_alert_currency"),
        sa.ForeignKeyConstraint(
            ["company_id", "projection_id", "projection_version"],
            [
                "finance.cash_flow_projection_snapshot.company_id",
                "finance.cash_flow_projection_snapshot.id",
                "finance.cash_flow_projection_snapshot.version",
            ],
            name="fk_cash_flow_alert_company_projection",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cash_flow_alert"),
        sa.UniqueConstraint("company_id", "id", name="uq_cash_flow_alert_company_id"),
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_alert_company_detected",
        "cash_flow_alert",
        ["company_id", "detected_at", "severity", "alert_type"],
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_alert_company_projection",
        "cash_flow_alert",
        ["company_id", "projection_id", "projection_version"],
        schema="finance",
    )
    op.execute(
        """
        CREATE FUNCTION finance.reject_cash_flow_alert_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF current_setting('erp.allow_cash_flow_alert_cleanup', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'cash flow alerts are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_cash_flow_alert_append_only
        BEFORE UPDATE OR DELETE ON finance.cash_flow_alert
        FOR EACH ROW EXECUTE FUNCTION finance.reject_cash_flow_alert_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_cash_flow_alert_append_only ON finance.cash_flow_alert")
    op.execute("DROP FUNCTION IF EXISTS finance.reject_cash_flow_alert_mutation()")
    op.drop_table("cash_flow_alert", schema="finance")

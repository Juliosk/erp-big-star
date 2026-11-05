"""Add durable conversion evidence to MRP planned orders.

Revision ID: 0054
Revises: 0053
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "planned_order",
        sa.Column("converted_production_order_id", sa.Uuid(), nullable=True),
        schema="production",
    )
    op.add_column(
        "planned_order",
        sa.Column("material_reservation_id", sa.Uuid(), nullable=True),
        schema="production",
    )
    op.add_column(
        "planned_order",
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        schema="production",
    )
    op.add_column(
        "planned_order",
        sa.Column("converted_by", sa.Uuid(), nullable=True),
        schema="production",
    )
    op.create_foreign_key(
        "fk_planned_order_converted_production_order",
        "planned_order",
        "production_order",
        ["company_id", "converted_production_order_id"],
        ["company_id", "id"],
        source_schema="production",
        referent_schema="production",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_planned_order_material_reservation",
        "planned_order",
        "inventory_reservation",
        ["company_id", "material_reservation_id"],
        ["company_id", "id"],
        source_schema="production",
        referent_schema="inventory",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_planned_order_converted_production_order",
        "planned_order",
        ["company_id", "converted_production_order_id"],
        schema="production",
    )
    op.create_unique_constraint(
        "uq_planned_order_material_reservation",
        "planned_order",
        ["company_id", "material_reservation_id"],
        schema="production",
    )
    op.create_check_constraint(
        "ck_planned_order_conversion_evidence",
        "planned_order",
        "(status = 'CONVERTED' AND converted_production_order_id IS NOT NULL "
        "AND material_reservation_id IS NOT NULL AND converted_at IS NOT NULL "
        "AND converted_by IS NOT NULL) OR (status <> 'CONVERTED' "
        "AND converted_production_order_id IS NULL AND material_reservation_id IS NULL "
        "AND converted_at IS NULL AND converted_by IS NULL)",
        schema="production",
    )
    op.create_index(
        "ix_planned_order_company_conversion",
        "planned_order",
        ["company_id", "status", "converted_at"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_planned_order_company_conversion",
        table_name="planned_order",
        schema="production",
    )
    op.drop_constraint(
        "ck_planned_order_conversion_evidence",
        "planned_order",
        schema="production",
        type_="check",
    )
    op.drop_constraint(
        "uq_planned_order_material_reservation",
        "planned_order",
        schema="production",
        type_="unique",
    )
    op.drop_constraint(
        "uq_planned_order_converted_production_order",
        "planned_order",
        schema="production",
        type_="unique",
    )
    op.drop_constraint(
        "fk_planned_order_material_reservation",
        "planned_order",
        schema="production",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_planned_order_converted_production_order",
        "planned_order",
        schema="production",
        type_="foreignkey",
    )
    op.drop_column("planned_order", "converted_by", schema="production")
    op.drop_column("planned_order", "converted_at", schema="production")
    op.drop_column("planned_order", "material_reservation_id", schema="production")
    op.drop_column(
        "planned_order",
        "converted_production_order_id",
        schema="production",
    )

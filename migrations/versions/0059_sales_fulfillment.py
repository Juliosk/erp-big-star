"""Create tenant-bound multichannel sales fulfillment persistence.

Revision ID: 0059
Revises: 0058
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MARKETPLACES = "('MERCADO_LIVRE', 'SHOPEE', 'NUVEMSHOP')"
_SHIPMENT_STATUSES = "('LABEL_CREATED', 'DISPATCHED')"
_LOG_EVENTS = (
    "('SEPARATION_CONFIRMED', 'LABEL_CREATED', 'DISPATCHED', "
    "'CHANNEL_SYNC_REQUESTED')"
)


def upgrade() -> None:
    op.create_table(
        "sales_shipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sales_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wms_shipment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", sa.String(24), nullable=False),
        sa.Column("external_order_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("carrier_code", sa.String(32), nullable=False),
        sa.Column("service_code", sa.String(32), nullable=False),
        sa.Column("tracking_code", sa.String(80), nullable=False),
        sa.Column("label_reference", sa.String(255), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            f"marketplace IN {_MARKETPLACES}",
            name=op.f("ck_sales_shipment_marketplace"),
        ),
        sa.CheckConstraint(
            f"status IN {_SHIPMENT_STATUSES}",
            name=op.f("ck_sales_shipment_status"),
        ),
        sa.CheckConstraint(
            "status != 'DISPATCHED' OR dispatched_at IS NOT NULL",
            name=op.f("ck_sales_shipment_dispatch_timestamp"),
        ),
        sa.CheckConstraint(
            "length(btrim(external_order_id)) BETWEEN 1 AND 128",
            name=op.f("ck_sales_shipment_external_order_id"),
        ),
        sa.CheckConstraint(
            "length(btrim(carrier_code)) BETWEEN 1 AND 32 "
            "AND length(btrim(service_code)) BETWEEN 1 AND 32",
            name=op.f("ck_sales_shipment_carrier_service"),
        ),
        sa.CheckConstraint(
            "tracking_code ~ '^[A-Z0-9][A-Z0-9._-]{0,79}$'",
            name=op.f("ck_sales_shipment_tracking_code"),
        ),
        sa.CheckConstraint(
            "length(btrim(label_reference)) BETWEEN 1 AND 255",
            name=op.f("ck_sales_shipment_label_reference"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_sales_shipment_version")
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sales_order_id"],
            ["sales.sales_order.company_id", "sales.sales_order.id"],
            name="fk_sales_shipment_sales_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "wms_shipment_id"],
            ["wms.shipment.company_id", "wms.shipment.id"],
            name="fk_sales_shipment_wms_shipment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "channel_config_id"],
            ["sales.sales_channel_config.company_id", "sales.sales_channel_config.id"],
            name="fk_sales_shipment_channel_config",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_shipment")),
        sa.UniqueConstraint(
            "company_id", "id", name=op.f("uq_sales_shipment_company_id")
        ),
        sa.UniqueConstraint(
            "company_id",
            "sales_order_id",
            name=op.f("uq_sales_shipment_order"),
        ),
        sa.UniqueConstraint(
            "company_id",
            "wms_shipment_id",
            name=op.f("uq_sales_shipment_wms_shipment"),
        ),
        sa.UniqueConstraint(
            "company_id",
            "carrier_code",
            "tracking_code",
            name=op.f("uq_sales_shipment_tracking"),
        ),
        schema="sales",
    )
    op.create_index(
        "ix_sales_shipment_company_status_time",
        "sales_shipment",
        ["company_id", "status", "dispatched_at", "id"],
        schema="sales",
    )
    op.create_index(
        "ix_sales_shipment_company_external",
        "sales_shipment",
        ["company_id", "marketplace", "account_id", "external_order_id"],
        schema="sales",
    )

    op.create_table(
        "sales_fulfillment_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence >= 1", name=op.f("ck_sales_fulfillment_log_sequence")
        ),
        sa.CheckConstraint(
            f"event_type IN {_LOG_EVENTS}",
            name=op.f("ck_sales_fulfillment_log_event_type"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name=op.f("ck_sales_fulfillment_log_payload"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "shipment_id"],
            ["sales.sales_shipment.company_id", "sales.sales_shipment.id"],
            name="fk_sales_fulfillment_log_shipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_fulfillment_log")),
        sa.UniqueConstraint(
            "company_id", "id", name=op.f("uq_sales_fulfillment_log_company_id")
        ),
        sa.UniqueConstraint(
            "company_id",
            "shipment_id",
            "sequence",
            name=op.f("uq_sales_fulfillment_log_sequence"),
        ),
        schema="sales",
    )
    op.create_index(
        "ix_sales_fulfillment_log_company_time",
        "sales_fulfillment_log",
        ["company_id", "occurred_at", "id"],
        schema="sales",
    )
    op.create_index(
        "ix_sales_fulfillment_log_shipment_event",
        "sales_fulfillment_log",
        ["company_id", "shipment_id", "event_type", "sequence"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("sales_fulfillment_log", schema="sales")
    op.drop_table("sales_shipment", schema="sales")

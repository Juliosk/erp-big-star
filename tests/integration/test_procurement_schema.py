"""Inspect M6 migration and ORM metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from erp.modules.admin.infrastructure import CompanyModel
from erp.modules.finance.infrastructure import PayableModel, ProvisionalEntryModel
from erp.modules.fiscal.infrastructure import InboundFiscalDocumentItemModel
from erp.modules.procurement.infrastructure import (
    GoodsReceiptModel,
    MatchingAuditLogModel,
    MatchingReevaluationModel,
    MatchingSessionItemModel,
    MatchingSessionModel,
    MatchingSourceCursorModel,
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseRequisitionModel,
    ReceiptItemModel,
    RequisitionItemModel,
    SupplierModel,
    SupplierSiteModel,
)
from erp.modules.product.infrastructure import ProductModel
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_procurement(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    return kind != "table" or obj.schema == "procurement"


@pytest.mark.integration
def test_procurement_migration_matches_orm_and_tenant_constraints() -> None:
    def verify(connection: Connection) -> None:
        assert CompanyModel.__table__.schema == "admin"
        assert ProvisionalEntryModel.__table__.schema == "finance"
        assert PayableModel.__table__.schema == "finance"
        assert InboundFiscalDocumentItemModel.__table__.schema == "fiscal"
        assert ProductModel.__table__.schema == "product"
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="procurement")) == {
            "purchase_order",
            "purchase_order_item",
            "purchase_requisition",
            "goods_receipt",
            "matching_audit_log",
            "matching_reevaluation",
            "matching_session",
            "matching_session_item",
            "matching_source_cursor",
            "receipt_item",
            "requisition_item",
            "supplier",
            "supplier_site",
        }
        for table, model in (
            ("supplier", SupplierModel),
            ("supplier_site", SupplierSiteModel),
            ("purchase_requisition", PurchaseRequisitionModel),
            ("requisition_item", RequisitionItemModel),
            ("purchase_order", PurchaseOrderModel),
            ("purchase_order_item", PurchaseOrderItemModel),
            ("goods_receipt", GoodsReceiptModel),
            ("receipt_item", ReceiptItemModel),
            ("matching_session", MatchingSessionModel),
            ("matching_session_item", MatchingSessionItemModel),
            ("matching_audit_log", MatchingAuditLogModel),
            ("matching_source_cursor", MatchingSourceCursorModel),
            ("matching_reevaluation", MatchingReevaluationModel),
        ):
            columns = {
                column["name"] for column in inspector.get_columns(table, schema="procurement")
            }
            assert columns == set(model.__table__.columns.keys())

        supplier_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supplier", "procurement")
        }
        assert (
            "company_id",
            "identity_kind",
            "identity_country_code",
            "identity_value",
        ) in supplier_uniques
        site_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("supplier_site", "procurement")
        }
        assert ("company_id", "code") in site_uniques
        requisition_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("purchase_requisition", "procurement")
        }
        order_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("purchase_order", "procurement")
        }
        assert ("company_id", "number") in requisition_uniques
        assert ("company_id", "number") in order_uniques
        receipt_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("goods_receipt", "procurement")
        }
        assert ("company_id", "number") in receipt_uniques
        receipt_fks = inspector.get_foreign_keys("goods_receipt", "procurement")
        assert (
            "company_id",
            "purchase_order_id",
        ) in {tuple(item["constrained_columns"]) for item in receipt_fks}
        reevaluation_fks = inspector.get_foreign_keys(
            "matching_reevaluation", "procurement"
        )
        assert (
            "company_id",
            "matching_session_id",
        ) in {tuple(item["constrained_columns"]) for item in reevaluation_fks}
        assert tuple(
            inspector.get_pk_constraint(
                "matching_source_cursor", "procurement"
            )["constrained_columns"]
        ) == (
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
        )
        site_fks = inspector.get_foreign_keys("supplier_site", "procurement")
        assert {
            tuple(item["constrained_columns"]): (
                item["referred_schema"],
                tuple(item["referred_columns"]),
            )
            for item in site_fks
        } == {
            ("company_id", "supplier_id"): (
                "procurement",
                ("company_id", "id"),
            )
        }
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_procurement,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        assert compare_metadata(context, Base.metadata) == []

    async def scenario() -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:
                await connection.run_sync(verify)
        finally:
            await database.dispose()

    asyncio.run(scenario())

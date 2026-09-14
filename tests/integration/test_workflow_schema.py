"""Inspect the M22 Workflow Core migration and ORM metadata alignment."""

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect

from erp.modules.admin.infrastructure import CompanyModel
from erp.modules.workflow.infrastructure import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Base, Database


def _only_workflow(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    """Compare only the M22 schema owned by this sprint."""
    return kind != "table" or obj.schema == "workflow"


@pytest.mark.integration
def test_workflow_core_migration_matches_orm_and_tenant_fks() -> None:
    def verify(connection: Connection) -> None:
        assert CompanyModel.__table__.schema == "admin"
        assert WorkflowDefinitionModel.__table__.schema == "workflow"
        assert WorkflowStepDefinitionModel.__table__.schema == "workflow"
        assert WorkflowInstanceModel.__table__.schema == "workflow"
        assert WorkflowStepInstanceModel.__table__.schema == "workflow"
        assert ApprovalDecisionModel.__table__.schema == "workflow"
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="workflow")) >= {
            "workflow_definition",
            "workflow_step_definition",
            "workflow_instance",
            "workflow_step_instance",
            "approval_decision",
        }
        for table, model in (
            ("workflow_definition", WorkflowDefinitionModel),
            ("workflow_step_definition", WorkflowStepDefinitionModel),
            ("workflow_instance", WorkflowInstanceModel),
            ("workflow_step_instance", WorkflowStepInstanceModel),
            ("approval_decision", ApprovalDecisionModel),
        ):
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table, schema="workflow")
            }
            assert set(columns) == set(model.__table__.columns.keys())
        definition_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "workflow_definition", "workflow"
            )
        }
        assert "uq_workflow_definition_company_code" in definition_uniques
        instance_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "workflow_instance", "workflow"
            )
        }
        assert "uq_workflow_instance_source_fingerprint" in instance_uniques
        step_definition_foreign_keys = inspector.get_foreign_keys(
            "workflow_step_definition", "workflow"
        )
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in step_definition_foreign_keys
        } == {
            ("company_id", "definition_id"): "workflow",
        }
        instance_foreign_keys = inspector.get_foreign_keys("workflow_instance", "workflow")
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in instance_foreign_keys
        } == {
            ("company_id", "definition_id"): "workflow",
        }
        decision_foreign_keys = inspector.get_foreign_keys(
            "approval_decision", "workflow"
        )
        assert {
            tuple(foreign_key["constrained_columns"]): foreign_key["referred_schema"]
            for foreign_key in decision_foreign_keys
        } == {
            ("company_id", "step_instance_id"): "workflow",
            ("company_id", "workflow_instance_id"): "workflow",
        }
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_workflow,
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

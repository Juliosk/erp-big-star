"""Integration tests for company-scoped M22 Workflow Core repositories."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from erp.modules.workflow.domain import (
    ApprovalDecision,
    ApprovalDecisionKind,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStepDefinition,
    WorkflowStepInstance,
)
from erp.modules.workflow.infrastructure import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowRepository,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


async def _cleanup_workflow(data: Fixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(
            delete(ApprovalDecisionModel).where(
                ApprovalDecisionModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowStepInstanceModel).where(
                WorkflowStepInstanceModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowInstanceModel).where(
                WorkflowInstanceModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowStepDefinitionModel).where(
                WorkflowStepDefinitionModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(
                WorkflowDefinitionModel.company_id.in_(company_ids)
            )
        )


@asynccontextmanager
async def workflow_fixture() -> AsyncIterator[Fixture]:
    async with fixture() as data:
        try:
            yield data
        finally:
            await _cleanup_workflow(data)


def _definition(company_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition.create(
        company_id=company_id,
        code=f"WF-{uuid4().hex[:8].upper()}",
        name="Aprovação comercial",
        source_module="SALES",
        source_type="QUOTE",
    )


def _step(company_id: UUID, *, sequence: int = 1) -> WorkflowStepDefinition:
    return WorkflowStepDefinition.create(
        company_id=company_id,
        sequence=sequence,
        code=f"STEP-{sequence}",
        name=f"Aprovação {sequence}",
        required_permission="workflow.approval.decide",
    )


def test_workflow_repository_persists_definitions_instances_and_decisions() -> None:
    async def scenario() -> None:
        async with (
            workflow_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            repository = WorkflowRepository(session, company_id=data.company_id)
            definition = _definition(data.company_id)
            first_step = _step(data.company_id)
            second_step = _step(data.company_id, sequence=2)
            await repository.add_definition(
                definition,
                steps=(first_step, second_step),
                actor_id=data.actor_id,
            )
            instance = WorkflowInstance.create(
                company_id=data.company_id,
                definition_id=definition.id,
                source_module="SALES",
                source_type="QUOTE",
                source_id=uuid4(),
                source_fingerprint="quote:v1",
                requested_by=data.actor_id,
            )
            active = WorkflowStepInstance.create(
                company_id=data.company_id,
                workflow_instance_id=instance.id,
                sequence=1,
                code=first_step.code,
                name=first_step.name,
                required_permission=first_step.required_permission,
                active=True,
            )
            waiting = WorkflowStepInstance.create(
                company_id=data.company_id,
                workflow_instance_id=instance.id,
                sequence=2,
                code=second_step.code,
                name=second_step.name,
                required_permission=second_step.required_permission,
            )
            await repository.add_instance(
                instance,
                steps=(active, waiting),
                actor_id=data.actor_id,
            )
            decision = ApprovalDecision.create(
                company_id=data.company_id,
                workflow_instance_id=instance.id,
                step_instance_id=active.id,
                decision=ApprovalDecisionKind.APPROVED,
                decided_by=data.actor_id,
                reason_code="OK",
                comment="Aprovado",
            )
            await repository.add_decision(decision)

            assert await repository.get_definition(definition.id) == definition
            assert await repository.find_active_definition(
                source_module="SALES", source_type="QUOTE"
            ) == definition
            assert await repository.list_definitions() == (definition,)
            assert await repository.list_step_definitions(
                definition_id=definition.id
            ) == (first_step, second_step)
            assert await repository.get_instance(instance.id) == instance
            assert await repository.list_instances() == (instance,)
            assert await repository.list_step_instances(
                workflow_instance_id=instance.id
            ) == (active, waiting)
            assert await repository.list_active_steps_for_permissions(
                frozenset({"workflow.approval.decide"})
            ) == (active,)
            assert await repository.list_decisions(
                workflow_instance_id=instance.id
            ) == (decision,)

    asyncio.run(scenario())


def test_workflow_repository_hides_foreign_company_records_and_rejects_scope_mismatch() -> None:
    async def scenario() -> None:
        async with workflow_fixture() as data, data.database.session() as session, session.begin():
            own_repo = WorkflowRepository(session, company_id=data.company_id)
            foreign_repo = WorkflowRepository(session, company_id=data.other_company_id)
            own = _definition(data.company_id)
            foreign = _definition(data.other_company_id)
            await own_repo.add_definition(own, steps=(_step(data.company_id),), actor_id=data.actor_id)
            await foreign_repo.add_definition(
                foreign,
                steps=(_step(data.other_company_id),),
                actor_id=data.actor_id,
            )

            assert await own_repo.list_definitions() == (own,)
            assert await foreign_repo.list_definitions() == (foreign,)
            assert await own_repo.get_definition(foreign.id) is None
            with pytest.raises(ApplicationError) as captured:
                await own_repo.add_definition(
                    _definition(data.other_company_id),
                    steps=(_step(data.other_company_id),),
                    actor_id=data.actor_id,
                )
            assert captured.value.code == "SCOPE_FORBIDDEN"

    asyncio.run(scenario())


def test_workflow_repository_rejects_duplicates_and_missing_references() -> None:
    async def scenario() -> None:
        async with workflow_fixture() as data:
            async with data.database.session() as session, session.begin():
                repository = WorkflowRepository(session, company_id=data.company_id)
                definition = _definition(data.company_id)
                await repository.add_definition(
                    definition,
                    steps=(_step(data.company_id),),
                    actor_id=data.actor_id,
                )
                async with session.begin_nested() as savepoint:
                    duplicate = WorkflowDefinition.create(
                        company_id=data.company_id,
                        code=definition.code,
                        name="Duplicada",
                        source_module="SALES",
                        source_type="QUOTE",
                    )
                    with pytest.raises(ApplicationError) as captured:
                        await repository.add_definition(
                            duplicate,
                            steps=(_step(data.company_id),),
                            actor_id=data.actor_id,
                        )
                    assert captured.value.code == "WORKFLOW_DEFINITION_CONFLICT"
                    await savepoint.rollback()

            async with data.database.session() as session, session.begin():
                repository = WorkflowRepository(session, company_id=data.company_id)
                missing = WorkflowInstance.create(
                    company_id=data.company_id,
                    definition_id=uuid4(),
                    source_module="SALES",
                    source_type="QUOTE",
                    source_id=uuid4(),
                    source_fingerprint="missing-definition",
                    requested_by=data.actor_id,
                )
                with pytest.raises(ApplicationError) as captured:
                    await repository.add_instance(
                        missing,
                        steps=(
                            WorkflowStepInstance.create(
                                company_id=data.company_id,
                                workflow_instance_id=missing.id,
                                sequence=1,
                                code="STEP-1",
                                name="Aprovação",
                                required_permission="workflow.approval.decide",
                                active=True,
                            ),
                        ),
                        actor_id=data.actor_id,
                    )
                assert captured.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())


def test_workflow_repository_updates_instances_and_steps_with_optimistic_lock() -> None:
    async def scenario() -> None:
        async with (
            workflow_fixture() as data,
            data.database.session() as session,
            session.begin(),
        ):
            repository = WorkflowRepository(session, company_id=data.company_id)
            definition = _definition(data.company_id)
            step_definition = _step(data.company_id)
            await repository.add_definition(
                definition,
                steps=(step_definition,),
                actor_id=data.actor_id,
            )
            instance = WorkflowInstance.create(
                company_id=data.company_id,
                definition_id=definition.id,
                source_module="SALES",
                source_type="QUOTE",
                source_id=uuid4(),
                source_fingerprint="quote:v2",
                requested_by=data.actor_id,
            )
            step = WorkflowStepInstance.create(
                company_id=data.company_id,
                workflow_instance_id=instance.id,
                sequence=1,
                code=step_definition.code,
                name=step_definition.name,
                required_permission=step_definition.required_permission,
                active=True,
            )
            await repository.add_instance(instance, steps=(step,), actor_id=data.actor_id)

            locked_instance = await repository.get_instance_for_update(instance.id)
            assert locked_instance == instance
            updated_step = await repository.update_step_instance(
                step.approve(actor_id=data.actor_id),
                actor_id=data.actor_id,
                expected_version=step.version,
            )
            updated_instance = await repository.update_instance(
                instance.approve_final(),
                actor_id=data.actor_id,
                expected_version=instance.version,
            )

            assert updated_step.version == 2
            assert updated_instance.version == 2
            assert updated_instance.status is WorkflowInstanceStatus.APPROVED

    asyncio.run(scenario())

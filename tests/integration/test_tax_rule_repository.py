"""M11 tax-rule repository integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from erp.modules.fiscal.domain import (
    FiscalFlow,
    InvalidTaxRuleError,
    TaxJurisdiction,
    TaxRateProfile,
    TaxRule,
    TaxRuleConflictError,
    TaxRuleCriteria,
    TaxRuleScopeError,
    TaxRuleStatus,
    TaxRuleVersionConflictError,
)
from erp.modules.fiscal.infrastructure import TaxRuleModel, TaxRuleRepository
from tests.integration.test_procurement_supplier_repository import (
    ProcurementFixture,
    procurement_fixture,
)

pytestmark = pytest.mark.integration


def _rule(data: ProcurementFixture, **changes: object) -> TaxRule:
    values: dict[str, object] = {
        "id": uuid4(),
        "company_id": data.company_id,
        "code": f"RULE-{uuid4().hex[:10].upper()}",
        "version_code": "V1",
        "criteria": TaxRuleCriteria(
            flow=FiscalFlow.OUTBOUND,
            ncm="95030099",
            cfop="5102",
            origin=TaxJurisdiction("BR", "SP", "3550308"),
            destination=TaxJurisdiction("BR", "RJ", "3304557"),
        ),
        "rates": TaxRateProfile(
            Decimal("0.1800"),
            Decimal("0.0165"),
            Decimal("0.0760"),
            Decimal("0.0000"),
        ),
        "effective_from": date(2026, 11, 1),
        "effective_until": date(2026, 12, 31),
        "created_by": uuid4(),
    }
    values.update(changes)
    return TaxRule(**values)  # type: ignore[arg-type]


@asynccontextmanager
async def tax_rule_fixture() -> AsyncIterator[tuple[ProcurementFixture, TaxRule]]:
    async with procurement_fixture() as data:
        rule = _rule(data)
        try:
            yield data, rule
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(TaxRuleModel).where(
                        TaxRuleModel.company_id.in_((data.company_id, data.other_company_id))
                    )
                )


def test_tax_rule_round_trip_lifecycle_filters_and_row_lock() -> None:
    async def scenario() -> None:
        async with (
            tax_rule_fixture() as (data, rule),
            data.database.session() as session,
            session.begin(),
        ):
            repository = TaxRuleRepository(session, company_id=data.company_id)
            await repository.add(rule, actor_id=data.actor_id)
            assert await repository.get(rule.id) == rule
            assert await repository.get_for_update(rule.id) == rule
            assert await repository.list(status=TaxRuleStatus.DRAFT) == (rule,)
            assert await repository.list(effective_on=date(2026, 11, 15)) == (rule,)
            assert await repository.list(effective_on=date(2027, 1, 1)) == ()

            active = rule.activate(actor_id=data.actor_id, occurred_at=datetime.now(UTC))
            assert await repository.save(active, actor_id=data.actor_id) == active
            retired = active.retire(occurred_at=datetime.now(UTC) + timedelta(seconds=1))
            await repository.save(retired, actor_id=data.actor_id)
            assert await repository.get(rule.id) == retired

    asyncio.run(scenario())


def test_tax_rule_repository_is_tenant_bound_and_translates_conflicts() -> None:
    async def scenario() -> None:
        async with (
            tax_rule_fixture() as (data, rule),
            data.database.session() as session,
            session.begin(),
        ):
            repository = TaxRuleRepository(session, company_id=data.company_id)
            await repository.add(rule, actor_id=data.actor_id)
            foreign = TaxRuleRepository(session, company_id=data.other_company_id)
            assert await foreign.get(rule.id) is None
            with pytest.raises(TaxRuleScopeError):
                await foreign.add(rule, actor_id=data.actor_id)

            duplicate = replace(rule, id=uuid4())
            savepoint = await session.begin_nested()
            with pytest.raises(TaxRuleConflictError):
                await repository.add(duplicate, actor_id=data.actor_id)
            await savepoint.rollback()

            active = rule.activate(actor_id=data.actor_id, occurred_at=datetime.now(UTC))
            await repository.save(active, actor_id=data.actor_id)
            with pytest.raises(TaxRuleVersionConflictError):
                await repository.save(active, actor_id=data.actor_id, expected_version=1)

    asyncio.run(scenario())


def test_tax_rule_repository_rejects_invalid_contract_and_snapshot_drift() -> None:
    async def scenario() -> None:
        async with (
            tax_rule_fixture() as (data, rule),
            data.database.session() as session,
            session.begin(),
        ):
            with pytest.raises(ValueError, match="company UUID"):
                TaxRuleRepository(session, company_id=UUID(int=0))
            repository = TaxRuleRepository(session, company_id=data.company_id)
            with pytest.raises(TypeError, match="TaxRule"):
                await repository.add(object(), actor_id=data.actor_id)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.add(rule, actor_id=UUID(int=0))
            with pytest.raises(ValueError, match="start draft"):
                await repository.add(
                    rule.activate(actor_id=data.actor_id, occurred_at=datetime.now(UTC)),
                    actor_id=data.actor_id,
                )
            await repository.add(rule, actor_id=data.actor_id)
            active = rule.activate(actor_id=data.actor_id, occurred_at=datetime.now(UTC))
            with pytest.raises(InvalidTaxRuleError, match="immutable"):
                await repository.save(
                    replace(active, code="CHANGED"),
                    actor_id=data.actor_id,
                )
            with pytest.raises(ValueError, match="version increment"):
                await repository.save(rule, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="limit"):
                await repository.list(limit=0)
            with pytest.raises(ValueError, match="offset"):
                await repository.list(offset=-1)
            with pytest.raises(ValueError, match="official"):
                await repository.list(status="DRAFT")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="date"):
                await repository.list(effective_on="2026-11-11")  # type: ignore[arg-type]

    asyncio.run(scenario())

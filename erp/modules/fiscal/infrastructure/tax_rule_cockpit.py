"""PostgreSQL projection for the fiscal tax-rule cockpit."""

from datetime import datetime
from uuid import UUID

from erp.modules.fiscal.application.cockpit import (
    FiscalCockpitRule,
    FiscalCockpitSnapshot,
)
from erp.modules.fiscal.domain import TaxRuleStatus
from erp.modules.fiscal.infrastructure.tax_rule_repository import TaxRuleRepository
from erp.platform.database import Database


class PostgresFiscalCockpitReader:
    """Load fiscal rule governance without exposing ORM models."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> FiscalCockpitSnapshot:
        async with self._database.session() as session:
            rules = await TaxRuleRepository(session, company_id=company_id).list(limit=limit)
        return FiscalCockpitSnapshot(
            company_id=company_id,
            generated_at=generated_at,
            total_rules=len(rules),
            draft_rules=sum(rule.status is TaxRuleStatus.DRAFT for rule in rules),
            active_rules=sum(rule.status is TaxRuleStatus.ACTIVE for rule in rules),
            retired_rules=sum(rule.status is TaxRuleStatus.RETIRED for rule in rules),
            rules=tuple(
                FiscalCockpitRule(
                    id=rule.id,
                    code=rule.code,
                    version_code=rule.version_code,
                    status=rule.status.value,
                    flow=rule.criteria.flow.value,
                    ncm=rule.criteria.ncm,
                    cfop=rule.criteria.cfop,
                    effective_from=rule.effective_from,
                    effective_until=rule.effective_until,
                    icms_rate=rule.rates.icms,
                    pis_rate=rule.rates.pis,
                    cofins_rate=rule.rates.cofins,
                    ipi_rate=rule.rates.ipi,
                    version=rule.version,
                )
                for rule in rules
            ),
        )


__all__ = ["PostgresFiscalCockpitReader"]

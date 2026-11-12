"""Tenant-bound persistence adapter for the M11 TaxRule aggregate."""

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from erp.modules.fiscal.infrastructure.tax_rule_model import TaxRuleModel


class TaxRuleRepository:
    """Persist tax rules without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, rule: TaxRule, *, actor_id: UUID) -> None:
        self._write_scope(rule, actor_id)
        if rule.version != 1 or rule.status is not TaxRuleStatus.DRAFT:
            raise ValueError("A new tax rule must start draft at version one.")
        now = datetime.now(UTC)
        self._session.add(
            TaxRuleModel(
                id=rule.id,
                company_id=rule.company_id,
                created_at=now,
                created_by=rule.created_by,
                **_values(rule, actor_id=actor_id, occurred_at=now),
            )
        )
        await self._flush()

    async def get(self, rule_id: UUID) -> TaxRule | None:
        model = await self._session.scalar(
            select(TaxRuleModel)
            .where(
                TaxRuleModel.company_id == self._company_id,
                TaxRuleModel.id == rule_id,
            )
            .execution_options(populate_existing=True)
        )
        return _rule(model) if model is not None else None

    async def get_for_update(self, rule_id: UUID) -> TaxRule | None:
        model = await self._session.scalar(
            select(TaxRuleModel)
            .where(
                TaxRuleModel.company_id == self._company_id,
                TaxRuleModel.id == rule_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return _rule(model) if model is not None else None

    async def list(
        self,
        *,
        status: TaxRuleStatus | None = None,
        effective_on: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[TaxRule, ...]:
        _page(limit, offset)
        statement = select(TaxRuleModel).where(TaxRuleModel.company_id == self._company_id)
        if status is not None:
            if not isinstance(status, TaxRuleStatus):
                raise ValueError("status must be an official tax-rule status.")
            statement = statement.where(TaxRuleModel.status == status.value)
        if effective_on is not None:
            if not isinstance(effective_on, date):
                raise ValueError("effective_on must be a date.")
            statement = statement.where(
                TaxRuleModel.effective_from <= effective_on,
                (TaxRuleModel.effective_until.is_(None))
                | (TaxRuleModel.effective_until >= effective_on),
            )
        models = await self._session.scalars(
            statement.order_by(TaxRuleModel.code, TaxRuleModel.version_code, TaxRuleModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_rule(model) for model in models)

    async def save(
        self,
        rule: TaxRule,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> TaxRule:
        self._write_scope(rule, actor_id)
        compare = rule.version - 1 if expected_version is None else expected_version
        if compare < 1 or rule.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self.get(rule.id)
        if current is None or current.version != compare:
            raise TaxRuleVersionConflictError(f"Tax rule expected version {compare} is stale.")
        _validate_frozen_state(current, rule)
        _validate_transition(current.status, rule.status)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(TaxRuleModel)
                .where(
                    TaxRuleModel.company_id == self._company_id,
                    TaxRuleModel.id == rule.id,
                    TaxRuleModel.version == compare,
                )
                .values(**_values(rule, actor_id=actor_id, occurred_at=datetime.now(UTC)))
            ),
        )
        if result.rowcount != 1:
            raise TaxRuleVersionConflictError(f"Tax rule expected version {compare} is stale.")
        await self._flush()
        return rule

    def _write_scope(self, rule: TaxRule, actor_id: UUID) -> None:
        if not isinstance(rule, TaxRule):
            raise TypeError("rule must be a TaxRule.")
        if rule.company_id != self._company_id:
            raise TaxRuleScopeError("Tax rule is outside the selected company.")
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("An explicit non-zero actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise TaxRuleConflictError(
                    "Tax-rule code and version already exist for this company."
                ) from error
            raise


def _values(rule: TaxRule, *, actor_id: UUID, occurred_at: datetime) -> dict[str, Any]:
    return {
        "code": rule.code,
        "version_code": rule.version_code,
        "flow": rule.criteria.flow.value,
        "ncm": rule.criteria.ncm,
        "cfop": rule.criteria.cfop,
        "origin_country_code": rule.criteria.origin.country_code,
        "origin_state_code": rule.criteria.origin.state_code,
        "origin_municipality_code": rule.criteria.origin.municipality_code,
        "destination_country_code": rule.criteria.destination.country_code,
        "destination_state_code": rule.criteria.destination.state_code,
        "destination_municipality_code": rule.criteria.destination.municipality_code,
        "icms_rate": rule.rates.icms,
        "pis_rate": rule.rates.pis,
        "cofins_rate": rule.rates.cofins,
        "ipi_rate": rule.rates.ipi,
        "effective_from": rule.effective_from,
        "effective_until": rule.effective_until,
        "status": rule.status.value,
        "activated_by": rule.activated_by,
        "activated_at": rule.activated_at,
        "retired_at": rule.retired_at,
        "version": rule.version,
        "updated_at": occurred_at,
        "updated_by": actor_id,
    }


def _rule(model: TaxRuleModel) -> TaxRule:
    return TaxRule(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        version_code=model.version_code,
        criteria=TaxRuleCriteria(
            flow=FiscalFlow(model.flow),
            ncm=model.ncm,
            cfop=model.cfop,
            origin=TaxJurisdiction(
                model.origin_country_code,
                model.origin_state_code,
                model.origin_municipality_code,
            ),
            destination=TaxJurisdiction(
                model.destination_country_code,
                model.destination_state_code,
                model.destination_municipality_code,
            ),
        ),
        rates=TaxRateProfile(
            icms=model.icms_rate,
            pis=model.pis_rate,
            cofins=model.cofins_rate,
            ipi=model.ipi_rate,
        ),
        effective_from=model.effective_from,
        effective_until=model.effective_until,
        created_by=model.created_by,
        status=TaxRuleStatus(model.status),
        version=model.version,
        activated_by=model.activated_by,
        activated_at=model.activated_at,
        retired_at=model.retired_at,
    )


def _validate_frozen_state(current: TaxRule, candidate: TaxRule) -> None:
    if (
        current.company_id != candidate.company_id
        or current.code != candidate.code
        or current.version_code != candidate.version_code
        or current.criteria != candidate.criteria
        or current.rates != candidate.rates
        or current.effective_from != candidate.effective_from
        or current.effective_until != candidate.effective_until
        or current.created_by != candidate.created_by
    ):
        raise InvalidTaxRuleError("Tax-rule identity, criteria, rates and validity are immutable.")


def _validate_transition(current: TaxRuleStatus, candidate: TaxRuleStatus) -> None:
    allowed = {
        TaxRuleStatus.DRAFT: {TaxRuleStatus.ACTIVE},
        TaxRuleStatus.ACTIVE: {TaxRuleStatus.RETIRED},
    }
    if candidate not in allowed.get(current, set()):
        raise InvalidTaxRuleError(
            f"Persistence transition {current.value} -> {candidate.value} is not allowed."
        )


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["TaxRuleRepository"]

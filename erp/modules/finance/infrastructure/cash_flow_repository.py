"""Tenant-bound persistence for immutable Cash Flow projection snapshots."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    BusinessDayConvention,
    CashAmount,
    CashFlowBucket,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowConflictError,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowHorizonKind,
    CashFlowItem,
    CashFlowMissingSource,
    CashFlowOrigin,
    CashFlowProjection,
    CashFlowScenario,
    CashFlowScopeError,
    CashFlowSourceGap,
    CashFlowSummary,
    FinanceVersionConflictError,
    LiquidityState,
    ProjectionGranularity,
)
from erp.modules.finance.infrastructure.cash_flow_model import (
    CashFlowAuditLogModel,
    CashFlowProjectionSnapshotModel,
    CashFlowScenarioDefinitionModel,
)


class CashFlowProjectionRepository:
    """Append Cash Flow versions without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, projection: CashFlowProjection, *, actor_id: UUID) -> None:
        self._write_scope(projection, actor_id)
        if projection.version != 1:
            raise ValueError("A new Cash Flow projection must start at version one.")
        await self._persist_scenario(projection.scenario, actor_id=actor_id, created_at=projection.calculated_at)
        self._session.add(_snapshot_model(projection, actor_id))
        await self._flush()
        self._session.add(_audit_model(projection, actor_id, action="CREATED"))
        await self._flush()

    async def save(
        self,
        projection: CashFlowProjection,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> None:
        self._write_scope(projection, actor_id)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer.")
        if projection.version != expected_version + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self._latest_model(projection.id, for_update=True)
        if current is None or current.version != expected_version:
            raise FinanceVersionConflictError(
                f"Cash Flow projection expected version {expected_version} is stale."
            )
        await self._persist_scenario(projection.scenario, actor_id=actor_id, created_at=projection.calculated_at)
        self._session.add(_snapshot_model(projection, actor_id))
        await self._flush()
        self._session.add(_audit_model(projection, actor_id, action="RECALCULATED"))
        await self._flush()

    async def get(
        self,
        projection_id: UUID,
        *,
        version: int | None = None,
    ) -> CashFlowProjection | None:
        _nonzero_uuid(projection_id, "projection_id")
        if version is not None and (type(version) is not int or version < 1):
            raise ValueError("version must be a positive integer when provided.")
        statement = select(CashFlowProjectionSnapshotModel).where(
            CashFlowProjectionSnapshotModel.company_id == self._company_id,
            CashFlowProjectionSnapshotModel.id == projection_id,
        )
        if version is None:
            statement = statement.order_by(CashFlowProjectionSnapshotModel.version.desc()).limit(1)
        else:
            statement = statement.where(CashFlowProjectionSnapshotModel.version == version)
        model = await self._session.scalar(statement.execution_options(populate_existing=True))
        if model is None:
            return None
        scenario = await self._scenario(model.scenario_id)
        return _projection(model, scenario)

    async def versions(self, projection_id: UUID) -> tuple[CashFlowProjection, ...]:
        _nonzero_uuid(projection_id, "projection_id")
        models = await self._session.scalars(
            select(CashFlowProjectionSnapshotModel)
            .where(
                CashFlowProjectionSnapshotModel.company_id == self._company_id,
                CashFlowProjectionSnapshotModel.id == projection_id,
            )
            .order_by(CashFlowProjectionSnapshotModel.version)
            .execution_options(populate_existing=True)
        )
        values = []
        for model in models:
            values.append(_projection(model, await self._scenario(model.scenario_id)))
        return tuple(values)

    async def list_latest(
        self,
        *,
        horizon: CashFlowHorizonKind,
        limit: int,
        offset: int,
    ) -> tuple[CashFlowProjection, ...]:
        """Return one latest immutable snapshot per projection for one horizon class."""
        if not isinstance(horizon, CashFlowHorizonKind):
            raise ValueError("horizon must be a CashFlowHorizonKind.")
        if type(limit) is not int or not 1 <= limit <= 101:
            raise ValueError("limit must be between 1 and 101.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset cannot be negative.")
        latest_versions = (
            select(
                CashFlowProjectionSnapshotModel.company_id.label("company_id"),
                CashFlowProjectionSnapshotModel.id.label("projection_id"),
                func.max(CashFlowProjectionSnapshotModel.version).label("version"),
            )
            .where(CashFlowProjectionSnapshotModel.company_id == self._company_id)
            .group_by(
                CashFlowProjectionSnapshotModel.company_id,
                CashFlowProjectionSnapshotModel.id,
            )
            .subquery()
        )
        duration = (
            CashFlowProjectionSnapshotModel.horizon_end
            - CashFlowProjectionSnapshotModel.horizon_start
        )
        if horizon is CashFlowHorizonKind.SHORT_TERM:
            horizon_filter = duration <= 90
        elif horizon is CashFlowHorizonKind.MEDIUM_TERM:
            horizon_filter = duration.between(91, 365)
        else:
            horizon_filter = duration > 365
        models = await self._session.scalars(
            select(CashFlowProjectionSnapshotModel)
            .join(
                latest_versions,
                (latest_versions.c.company_id == CashFlowProjectionSnapshotModel.company_id)
                & (latest_versions.c.projection_id == CashFlowProjectionSnapshotModel.id)
                & (latest_versions.c.version == CashFlowProjectionSnapshotModel.version),
            )
            .where(
                CashFlowProjectionSnapshotModel.company_id == self._company_id,
                horizon_filter,
            )
            .order_by(
                CashFlowProjectionSnapshotModel.as_of.desc(),
                CashFlowProjectionSnapshotModel.id,
            )
            .offset(offset)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        values = []
        for model in models:
            values.append(_projection(model, await self._scenario(model.scenario_id)))
        return tuple(values)

    async def claim_latest(self, projection_id: UUID) -> CashFlowProjection | None:
        """Claim the latest version without waiting for a concurrent projection writer."""
        _nonzero_uuid(projection_id, "projection_id")
        latest_version = (
            select(func.max(CashFlowProjectionSnapshotModel.version))
            .where(
                CashFlowProjectionSnapshotModel.company_id == self._company_id,
                CashFlowProjectionSnapshotModel.id == projection_id,
            )
            .scalar_subquery()
        )
        model = await self._session.scalar(
            select(CashFlowProjectionSnapshotModel)
            .where(
                CashFlowProjectionSnapshotModel.company_id == self._company_id,
                CashFlowProjectionSnapshotModel.id == projection_id,
                CashFlowProjectionSnapshotModel.version == latest_version,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if model is None:
            return None
        return _projection(model, await self._scenario(model.scenario_id))

    async def audit_log(self, projection_id: UUID) -> tuple[CashFlowAuditLogModel, ...]:
        _nonzero_uuid(projection_id, "projection_id")
        values = await self._session.scalars(
            select(CashFlowAuditLogModel)
            .where(
                CashFlowAuditLogModel.company_id == self._company_id,
                CashFlowAuditLogModel.projection_id == projection_id,
            )
            .order_by(CashFlowAuditLogModel.projection_version)
        )
        return tuple(values)

    async def _latest_model(
        self,
        projection_id: UUID,
        *,
        for_update: bool,
    ) -> CashFlowProjectionSnapshotModel | None:
        statement = (
            select(CashFlowProjectionSnapshotModel)
            .where(
                CashFlowProjectionSnapshotModel.company_id == self._company_id,
                CashFlowProjectionSnapshotModel.id == projection_id,
            )
            .order_by(CashFlowProjectionSnapshotModel.version.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(
            CashFlowProjectionSnapshotModel | None,
            await self._session.scalar(statement),
        )

    async def _scenario(self, scenario_id: UUID) -> CashFlowScenarioDefinitionModel:
        model = await self._session.scalar(
            select(CashFlowScenarioDefinitionModel).where(
                CashFlowScenarioDefinitionModel.company_id == self._company_id,
                CashFlowScenarioDefinitionModel.id == scenario_id,
            )
        )
        if model is None:
            raise CashFlowConflictError("Cash Flow snapshot references a missing scenario definition.")
        return model

    async def _persist_scenario(
        self,
        scenario: CashFlowScenario,
        *,
        actor_id: UUID,
        created_at: datetime,
    ) -> None:
        current = await self._session.scalar(
            select(CashFlowScenarioDefinitionModel).where(
                CashFlowScenarioDefinitionModel.company_id == self._company_id,
                CashFlowScenarioDefinitionModel.id == scenario.id,
            )
        )
        if current is None:
            self._session.add(_scenario_model(scenario, self._company_id, actor_id, created_at))
            await self._flush()
            return
        if _scenario(current) != scenario:
            raise CashFlowConflictError("Scenario identity already exists with another definition.")

    def _write_scope(self, projection: CashFlowProjection, actor_id: UUID) -> None:
        if not isinstance(projection, CashFlowProjection):
            raise TypeError("projection must be a CashFlowProjection.")
        if projection.company_id != self._company_id:
            raise CashFlowScopeError("Cash Flow projection is outside the selected company.")
        _nonzero_uuid(actor_id, "actor_id")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise CashFlowConflictError(
                    "Cash Flow scenario or projection version already exists for this company."
                ) from error
            raise


def _scenario_model(
    scenario: CashFlowScenario,
    company_id: UUID,
    actor_id: UUID,
    created_at: datetime,
) -> CashFlowScenarioDefinitionModel:
    return CashFlowScenarioDefinitionModel(
        id=scenario.id,
        company_id=company_id,
        name=scenario.name,
        receivable_delay_days=scenario.receivable_delay_days,
        cost_variation_rate=scenario.cost_variation_rate,
        business_day_convention=scenario.business_day_convention.value,
        version=1,
        created_at=created_at,
        created_by=actor_id,
    )


def _scenario(model: CashFlowScenarioDefinitionModel) -> CashFlowScenario:
    return CashFlowScenario(
        id=model.id,
        name=model.name,
        receivable_delay_days=model.receivable_delay_days,
        cost_variation_rate=model.cost_variation_rate,
        business_day_convention=BusinessDayConvention(model.business_day_convention),
    )


def _snapshot_model(
    projection: CashFlowProjection,
    actor_id: UUID,
) -> CashFlowProjectionSnapshotModel:
    return CashFlowProjectionSnapshotModel(
        id=projection.id,
        company_id=projection.company_id,
        version=projection.version,
        scenario_id=projection.scenario.id,
        as_of=projection.as_of,
        calculated_at=projection.calculated_at,
        horizon_start=projection.horizon.start_on,
        horizon_end=projection.horizon.end_on,
        granularity=projection.granularity.value,
        currency=projection.opening_balance.currency,
        opening_balance=projection.opening_balance.amount,
        minimum_reserve=projection.minimum_reserve.amount,
        operational_closing_balance=projection.summary.operational_closing_balance.amount,
        scenario_closing_balance=projection.summary.scenario_closing_balance.amount,
        liquidity_state=projection.liquidity_state.value,
        snapshot=_snapshot(projection),
        created_at=projection.calculated_at,
        created_by=actor_id,
    )


def _audit_model(
    projection: CashFlowProjection,
    actor_id: UUID,
    *,
    action: str,
) -> CashFlowAuditLogModel:
    return CashFlowAuditLogModel(
        id=uuid4(),
        company_id=projection.company_id,
        projection_id=projection.id,
        projection_version=projection.version,
        action=action,
        occurred_at=projection.calculated_at,
        actor_id=actor_id,
        details={
            "scenario_id": str(projection.scenario.id),
            "liquidity_state": projection.liquidity_state.value,
            "bucket_count": len(projection.buckets),
            "deferred_item_count": len(projection.deferred_items),
            "source_gap_count": len(projection.source_gaps),
        },
    )


def _snapshot(projection: CashFlowProjection) -> dict[str, Any]:
    return {
        "source_items": [_item_payload(item) for item in projection.source_items],
        "projected_items": [_item_payload(item) for item in projection.projected_items],
        "deferred_items": [_item_payload(item) for item in projection.deferred_items],
        "source_gaps": [_gap_payload(gap) for gap in projection.source_gaps],
        "buckets": [_bucket_payload(bucket) for bucket in projection.buckets],
        "summary": _summary_payload(projection.summary),
    }


def _item_payload(item: CashFlowItem) -> dict[str, Any]:
    return {
        "company_id": str(item.company_id),
        "amount": str(item.amount.amount),
        "currency": item.amount.currency,
        "occurs_on": item.occurs_on.isoformat(),
        "direction": item.direction.value,
        "category": item.category.value,
        "certainty": item.certainty.value,
        "origin": item.origin.value,
        "reference_id": str(item.reference_id) if item.reference_id else None,
    }


def _item(value: Mapping[str, Any]) -> CashFlowItem:
    reference = value.get("reference_id")
    return CashFlowItem(
        company_id=UUID(str(value["company_id"])),
        amount=CashAmount(Decimal(str(value["amount"])), str(value["currency"])),
        occurs_on=date.fromisoformat(str(value["occurs_on"])),
        direction=CashFlowDirection(str(value["direction"])),
        category=CashFlowCategory(str(value["category"])),
        certainty=CashFlowCertainty(str(value["certainty"])),
        origin=CashFlowOrigin(str(value["origin"])),
        reference_id=UUID(str(reference)) if reference else None,
    )


def _horizon_payload(value: CashFlowDateHorizon) -> dict[str, str]:
    return {"start_on": value.start_on.isoformat(), "end_on": value.end_on.isoformat()}


def _horizon(value: Mapping[str, Any]) -> CashFlowDateHorizon:
    return CashFlowDateHorizon(
        date.fromisoformat(str(value["start_on"])),
        date.fromisoformat(str(value["end_on"])),
    )


def _gap_payload(gap: CashFlowSourceGap) -> dict[str, Any]:
    return {
        "company_id": str(gap.company_id),
        "source": gap.source.value,
        "horizon": _horizon_payload(gap.horizon),
        "reason": gap.reason,
    }


def _gap(value: Mapping[str, Any]) -> CashFlowSourceGap:
    return CashFlowSourceGap(
        company_id=UUID(str(value["company_id"])),
        source=CashFlowMissingSource(str(value["source"])),
        horizon=_horizon(cast(Mapping[str, Any], value["horizon"])),
        reason=str(value["reason"]),
    )


def _amount_payload(value: CashAmount) -> dict[str, str]:
    return {"amount": str(value.amount), "currency": value.currency}


def _amount(value: Mapping[str, Any]) -> CashAmount:
    return CashAmount(Decimal(str(value["amount"])), str(value["currency"]))


def _bucket_payload(bucket: CashFlowBucket) -> dict[str, Any]:
    return {
        "start_on": bucket.start_on.isoformat(),
        "end_on": bucket.end_on.isoformat(),
        "operational_opening_balance": _amount_payload(bucket.operational_opening_balance),
        "operational_inflows": _amount_payload(bucket.operational_inflows),
        "operational_outflows": _amount_payload(bucket.operational_outflows),
        "operational_closing_balance": _amount_payload(bucket.operational_closing_balance),
        "scenario_opening_balance": _amount_payload(bucket.scenario_opening_balance),
        "scenario_inflows": _amount_payload(bucket.scenario_inflows),
        "scenario_outflows": _amount_payload(bucket.scenario_outflows),
        "scenario_closing_balance": _amount_payload(bucket.scenario_closing_balance),
        "liquidity_state": bucket.liquidity_state.value,
    }


def _bucket(value: Mapping[str, Any]) -> CashFlowBucket:
    def amount(field: str) -> CashAmount:
        return _amount(cast(Mapping[str, Any], value[field]))

    return CashFlowBucket(
        start_on=date.fromisoformat(str(value["start_on"])),
        end_on=date.fromisoformat(str(value["end_on"])),
        operational_opening_balance=amount("operational_opening_balance"),
        operational_inflows=amount("operational_inflows"),
        operational_outflows=amount("operational_outflows"),
        operational_closing_balance=amount("operational_closing_balance"),
        scenario_opening_balance=amount("scenario_opening_balance"),
        scenario_inflows=amount("scenario_inflows"),
        scenario_outflows=amount("scenario_outflows"),
        scenario_closing_balance=amount("scenario_closing_balance"),
        liquidity_state=LiquidityState(str(value["liquidity_state"])),
    )


def _summary_payload(summary: CashFlowSummary) -> dict[str, Any]:
    return {
        "company_id": str(summary.company_id),
        "horizon": _horizon_payload(summary.horizon),
        "currency": summary.currency,
        "opening_balance": _amount_payload(summary.opening_balance),
        "realized_inflows": _amount_payload(summary.realized_inflows),
        "realized_outflows": _amount_payload(summary.realized_outflows),
        "committed_inflows": _amount_payload(summary.committed_inflows),
        "committed_outflows": _amount_payload(summary.committed_outflows),
        "scenario_inflows": _amount_payload(summary.scenario_inflows),
        "scenario_outflows": _amount_payload(summary.scenario_outflows),
        "operational_closing_balance": _amount_payload(summary.operational_closing_balance),
        "scenario_closing_balance": _amount_payload(summary.scenario_closing_balance),
        "liquidity_state": summary.liquidity_state.value,
        "source_gaps": [_gap_payload(gap) for gap in summary.source_gaps],
    }


def _summary(value: Mapping[str, Any]) -> CashFlowSummary:
    def amount(field: str) -> CashAmount:
        return _amount(cast(Mapping[str, Any], value[field]))

    return CashFlowSummary(
        company_id=UUID(str(value["company_id"])),
        horizon=_horizon(cast(Mapping[str, Any], value["horizon"])),
        currency=str(value["currency"]),
        opening_balance=amount("opening_balance"),
        realized_inflows=amount("realized_inflows"),
        realized_outflows=amount("realized_outflows"),
        committed_inflows=amount("committed_inflows"),
        committed_outflows=amount("committed_outflows"),
        scenario_inflows=amount("scenario_inflows"),
        scenario_outflows=amount("scenario_outflows"),
        operational_closing_balance=amount("operational_closing_balance"),
        scenario_closing_balance=amount("scenario_closing_balance"),
        liquidity_state=LiquidityState(str(value["liquidity_state"])),
        source_gaps=tuple(
            _gap(cast(Mapping[str, Any], gap)) for gap in cast(list[Any], value["source_gaps"])
        ),
    )


def _projection(
    model: CashFlowProjectionSnapshotModel,
    scenario_model: CashFlowScenarioDefinitionModel,
) -> CashFlowProjection:
    payload = cast(Mapping[str, Any], model.snapshot)

    def items(field: str) -> tuple[CashFlowItem, ...]:
        return tuple(
            _item(cast(Mapping[str, Any], item)) for item in cast(list[Any], payload[field])
        )

    return CashFlowProjection(
        id=model.id,
        company_id=model.company_id,
        as_of=model.as_of,
        calculated_at=model.calculated_at,
        horizon=CashFlowDateHorizon(model.horizon_start, model.horizon_end),
        granularity=ProjectionGranularity(model.granularity),
        opening_balance=CashAmount(model.opening_balance, model.currency),
        minimum_reserve=CashAmount(model.minimum_reserve, model.currency),
        scenario=_scenario(scenario_model),
        source_items=items("source_items"),
        projected_items=items("projected_items"),
        deferred_items=items("deferred_items"),
        source_gaps=tuple(
            _gap(cast(Mapping[str, Any], gap))
            for gap in cast(list[Any], payload["source_gaps"])
        ),
        buckets=tuple(
            _bucket(cast(Mapping[str, Any], bucket))
            for bucket in cast(list[Any], payload["buckets"])
        ),
        summary=_summary(cast(Mapping[str, Any], payload["summary"])),
        version=model.version,
    )


def _nonzero_uuid(value: UUID, field_name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field_name} must be a non-zero UUID.")
    return value


__all__ = ["CashFlowProjectionRepository"]

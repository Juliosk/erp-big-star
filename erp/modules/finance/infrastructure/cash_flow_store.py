"""Session-owning PostgreSQL adapter for Cash Flow HTTP operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from erp.modules.finance.application import (
    CashFlowCompositionService,
    ComposeCashFlowProjection,
    UnavailableReceivableProvider,
)
from erp.modules.finance.application.cash_flow_alerts import (
    CashFlowAlertMetadata,
    CashFlowAlertService,
)
from erp.modules.finance.application.cash_flow_api import (
    CashFlowAlertPage,
    CashFlowAlertView,
    CashFlowCommandMetadata,
    CashFlowMutationResult,
    CashFlowProjectionPage,
    RefreshCashFlowProjection,
    SimulateCashFlowScenario,
)
from erp.modules.finance.domain import (
    BusinessCalendar,
    CashFlowAlertEngine,
    CashFlowAlertPolicy,
    CashFlowAlertSource,
    CashFlowCertainty,
    CashFlowConflictError,
    CashFlowEngine,
    CashFlowHorizonKind,
    CashFlowOrigin,
    CashFlowProjection,
    CashFlowProjectionInput,
    FinanceVersionConflictError,
)
from erp.modules.finance.infrastructure.cash_flow_alert_model import CashFlowAlertModel
from erp.modules.finance.infrastructure.cash_flow_alerts import (
    PostgresCashFlowAlertRecorder,
)
from erp.modules.finance.infrastructure.cash_flow_repository import (
    CashFlowProjectionRepository,
)
from erp.modules.finance.infrastructure.cash_flow_sources import (
    PostgresBankPositionProvider,
    PostgresPayableCommitmentProvider,
)
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresCashFlowStore:
    """Keep transaction/idempotency details outside the application service."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)
        self._engine = CashFlowEngine(BusinessCalendar())

    async def list_alerts(
        self,
        company_id: UUID,
        *,
        projection_id: UUID | None,
        severity: str | None,
        page: int,
        page_size: int,
    ) -> CashFlowAlertPage:
        statement = select(CashFlowAlertModel).where(
            CashFlowAlertModel.company_id == company_id
        )
        if projection_id is not None:
            statement = statement.where(
                CashFlowAlertModel.projection_id == projection_id
            )
        if severity is not None:
            statement = statement.where(CashFlowAlertModel.severity == severity)
        statement = (
            statement.order_by(
                CashFlowAlertModel.detected_at.desc(), CashFlowAlertModel.id
            )
            .limit(page_size + 1)
            .offset((page - 1) * page_size)
        )
        async with self._database.session() as session:
            values = tuple(await session.scalars(statement))
        return CashFlowAlertPage(
            items=tuple(_alert_view(item) for item in values[:page_size]),
            page=page,
            page_size=page_size,
            has_more=len(values) > page_size,
        )

    async def list_latest(
        self,
        company_id: UUID,
        *,
        horizon: CashFlowHorizonKind,
        page: int,
        page_size: int,
    ) -> CashFlowProjectionPage:
        async with self._database.session() as session:
            values = await CashFlowProjectionRepository(
                session, company_id=company_id
            ).list_latest(
                horizon=horizon,
                limit=page_size + 1,
                offset=(page - 1) * page_size,
            )
        return CashFlowProjectionPage(
            items=values[:page_size],
            page=page,
            page_size=page_size,
            has_more=len(values) > page_size,
        )

    async def get(
        self, company_id: UUID, projection_id: UUID
    ) -> CashFlowProjection | None:
        async with self._database.session() as session:
            return await CashFlowProjectionRepository(
                session, company_id=company_id
            ).get(projection_id)

    async def project(
        self,
        command: ComposeCashFlowProjection,
        *,
        actor_id: UUID,
        idempotency_key: str,
        metadata: CashFlowCommandMetadata,
    ) -> CashFlowMutationResult:
        payload = _compose_payload(command)
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"cash-flow:{command.company_id}:{actor_id}",
                operation="finance.cash-flow.project",
                key=idempotency_key,
                payload=payload,
            )
            repository = CashFlowProjectionRepository(
                session, company_id=command.company_id
            )
            if decision.replayed:
                projection = await _replayed_projection(repository, decision.response_body)
                return CashFlowMutationResult(projection, True, True, None)
            if await repository.get(command.projection_id) is not None:
                raise ApplicationError(
                    code="CASH_FLOW_PROJECTION_EXISTS",
                    message="Cash Flow projection already exists; use the refresh endpoint.",
                    status_code=409,
                )
            try:
                result = await self._composition(session, repository).compose(
                    command, actor_id=actor_id
                )
            except CashFlowConflictError as error:
                raise _cash_flow_conflict(error) from error
            await self._record_alerts(
                session,
                result.projection,
                source=CashFlowAlertSource.PROJECTION,
                actor_id=actor_id,
                metadata=metadata,
                detected_at=command.calculated_at,
            )
            response_body = {
                "projection_id": str(result.projection.id),
                "version": result.projection.version,
            }
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=response_body
            )
            return CashFlowMutationResult(result.projection, False, True, None)

    async def refresh(
        self,
        command: RefreshCashFlowProjection,
        *,
        actor_id: UUID,
    ) -> CashFlowMutationResult:
        payload = {
            "company_id": str(command.company_id),
            "projection_id": str(command.projection_id),
            "expected_version": command.expected_version,
        }
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"cash-flow:{command.company_id}:{actor_id}",
                operation="finance.cash-flow.refresh",
                key=command.idempotency_key,
                payload=payload,
            )
            repository = CashFlowProjectionRepository(
                session, company_id=command.company_id
            )
            if decision.replayed:
                projection = await _replayed_projection(repository, decision.response_body)
                return CashFlowMutationResult(
                    projection, True, True, command.expected_version
                )
            current = await _current_projection(repository, command.projection_id)
            _require_version(current.version, command.expected_version)
            predicted = tuple(
                item
                for item in current.source_items
                if item.certainty is CashFlowCertainty.SCENARIO
                and item.origin is CashFlowOrigin.MANUAL_SCENARIO
            )
            compose = ComposeCashFlowProjection(
                projection_id=current.id,
                company_id=current.company_id,
                as_of=current.as_of,
                calculated_at=command.calculated_at,
                horizon=current.horizon,
                granularity=current.granularity,
                minimum_reserve=current.minimum_reserve,
                scenario=current.scenario,
                predicted_items=predicted,
                currency=current.summary.currency,
            )
            try:
                result = await self._composition(session, repository).compose(
                    compose, actor_id=actor_id
                )
            except FinanceVersionConflictError as error:
                raise _version_conflict(error) from error
            await self._record_alerts(
                session,
                result.projection,
                source=CashFlowAlertSource.PROJECTION,
                actor_id=actor_id,
                metadata=command.metadata,
                detected_at=command.calculated_at,
            )
            response_body = {
                "projection_id": str(result.projection.id),
                "version": result.projection.version,
            }
            await self._idempotency.complete(
                session, decision, response_status=200, response_body=response_body
            )
            return CashFlowMutationResult(
                result.projection, False, True, current.version
            )

    async def simulate(
        self,
        command: SimulateCashFlowScenario,
        *,
        actor_id: UUID,
    ) -> CashFlowMutationResult:
        payload = {
            "company_id": str(command.company_id),
            "projection_id": str(command.projection_id),
            "expected_version": command.expected_version,
            "scenario_id": str(command.scenario_id),
            "name": command.name,
            "receivable_delay_days": command.receivable_delay_days,
            "cost_variation_rate": str(command.cost_variation_rate),
            "business_day_convention": command.business_day_convention.value,
        }
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"cash-flow:{command.company_id}:{actor_id}",
                operation="finance.cash-flow.scenario",
                key=command.idempotency_key,
                payload=payload,
            )
            repository = CashFlowProjectionRepository(
                session, company_id=command.company_id
            )
            calculated_at = command.calculated_at
            if decision.replayed:
                body = _response_body(decision.response_body)
                base_version = int(body["base_version"])
                calculated_at = datetime.fromisoformat(str(body["calculated_at"]))
                base = await repository.get(command.projection_id, version=base_version)
                if base is None:
                    raise RuntimeError("Idempotent Cash Flow base snapshot is missing.")
                projection = self._simulate(base, command, calculated_at)
                return CashFlowMutationResult(projection, True, False, base.version)
            base = await _current_projection(repository, command.projection_id)
            _require_version(base.version, command.expected_version)
            projection = self._simulate(base, command, calculated_at)
            await self._record_alerts(
                session,
                projection,
                source=CashFlowAlertSource.SCENARIO,
                actor_id=actor_id,
                metadata=command.metadata,
                detected_at=calculated_at,
            )
            await self._idempotency.complete(
                session,
                decision,
                response_status=200,
                response_body={
                    "base_version": base.version,
                    "calculated_at": calculated_at.isoformat(),
                },
            )
            return CashFlowMutationResult(projection, False, False, base.version)

    async def _record_alerts(
        self,
        session: Any,
        projection: CashFlowProjection,
        *,
        source: CashFlowAlertSource,
        actor_id: UUID,
        metadata: CashFlowCommandMetadata,
        detected_at: datetime,
    ) -> None:
        await CashFlowAlertService(
            CashFlowAlertEngine(CashFlowAlertPolicy()),
            PostgresCashFlowAlertRecorder(session),
        ).evaluate_and_record(
            projection,
            source=source,
            metadata=CashFlowAlertMetadata(
                actor_id=actor_id,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                detected_at=detected_at,
                source_ip=metadata.source_ip,
            ),
        )

    def _simulate(
        self,
        base: CashFlowProjection,
        command: SimulateCashFlowScenario,
        calculated_at: datetime,
    ) -> CashFlowProjection:
        authoritative = tuple(
            item
            for item in base.source_items
            if item.certainty is not CashFlowCertainty.SCENARIO
        )
        return self._engine.project(
            CashFlowProjectionInput(
                projection_id=base.id,
                company_id=base.company_id,
                as_of=base.as_of,
                calculated_at=calculated_at,
                horizon=base.horizon,
                granularity=base.granularity,
                opening_balance=base.opening_balance,
                minimum_reserve=base.minimum_reserve,
                scenario=command.scenario(),
                items=authoritative,
                source_gaps=base.source_gaps,
                version=base.version,
            )
        )

    def _composition(
        self,
        session: Any,
        repository: CashFlowProjectionRepository,
    ) -> CashFlowCompositionService:
        return CashFlowCompositionService(
            engine=self._engine,
            bank_positions=PostgresBankPositionProvider(session),
            payables=PostgresPayableCommitmentProvider(session),
            receivables=UnavailableReceivableProvider(),
            projections=repository,
        )


def _compose_payload(command: ComposeCashFlowProjection) -> dict[str, object]:
    return {
        "company_id": str(command.company_id),
        "projection_id": str(command.projection_id),
        "as_of": command.as_of.isoformat(),
        "horizon_end": command.horizon.end_on.isoformat(),
        "granularity": command.granularity.value,
        "minimum_reserve": str(command.minimum_reserve.amount),
        "currency": command.currency,
        "scenario": {
            "id": str(command.scenario.id),
            "name": command.scenario.name,
            "receivable_delay_days": command.scenario.receivable_delay_days,
            "cost_variation_rate": str(command.scenario.cost_variation_rate),
            "business_day_convention": command.scenario.business_day_convention.value,
        },
    }


def _alert_view(value: CashFlowAlertModel) -> CashFlowAlertView:
    return CashFlowAlertView(
        id=value.id,
        projection_id=value.projection_id,
        projection_version=value.projection_version,
        source=value.source,
        alert_type=value.alert_type,
        severity=value.severity,
        dimension=value.dimension,
        subject_key=value.subject_key,
        breach_on=value.breach_on,
        actual_value=value.actual_value,
        threshold_value=value.threshold_value,
        currency=value.currency,
        details=dict(value.details),
        detected_at=value.detected_at,
    )


async def _current_projection(
    repository: CashFlowProjectionRepository,
    projection_id: UUID,
) -> CashFlowProjection:
    projection = await repository.get(projection_id)
    if projection is None:
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND",
            message="Cash Flow projection not found in the selected company.",
            status_code=404,
        )
    return projection


async def _replayed_projection(
    repository: CashFlowProjectionRepository,
    response_body: dict[str, Any] | None,
) -> CashFlowProjection:
    body = _response_body(response_body)
    projection = await repository.get(
        UUID(str(body["projection_id"])), version=int(body["version"])
    )
    if projection is None:
        raise RuntimeError("Idempotent Cash Flow snapshot is missing.")
    return projection


def _response_body(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        raise RuntimeError("Completed idempotency record has no response body.")
    return value


def _require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message=f"Cash Flow projection expected version {expected}, current version is {actual}.",
            status_code=409,
        )


def _version_conflict(error: Exception) -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT", message=str(error), status_code=409
    )


def _cash_flow_conflict(error: Exception) -> ApplicationError:
    return ApplicationError(
        code="CASH_FLOW_CONFLICT", message=str(error), status_code=409
    )


__all__ = ["PostgresCashFlowStore"]

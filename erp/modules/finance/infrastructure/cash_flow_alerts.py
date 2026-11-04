"""Atomic persistence, Audit and Outbox effects for Cash Flow alerts."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.cash_flow_alerts import (
    CashFlowAlertMetadata,
    CashFlowAlertRecordResult,
)
from erp.modules.finance.domain import (
    CashFlowAlertPolicy,
    CashFlowAlertType,
    CashFlowRiskAlert,
)
from erp.modules.finance.infrastructure.cash_flow_alert_model import CashFlowAlertModel
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

CASH_FLOW_LIQUIDITY_ALERT_TRIGGERED = "CashFlowLiquidityAlertTriggered"
CASH_FLOW_CONCENTRATION_ALERT_TRIGGERED = "CashFlowConcentrationAlertTriggered"
CASH_FLOW_SENSITIVITY_ALERT_TRIGGERED = "CashFlowSensitivityAlertTriggered"


class PostgresCashFlowAlertRecorder:
    """Stage each new deterministic alert and its observable effects once."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        alerts: tuple[CashFlowRiskAlert, ...],
        *,
        policy: CashFlowAlertPolicy,
        metadata: CashFlowAlertMetadata,
    ) -> tuple[CashFlowAlertRecordResult, ...]:
        results = []
        for alert in alerts:
            inserted = await self._insert(alert, policy=policy, metadata=metadata)
            if not inserted:
                continue
            snapshot = _snapshot(alert, policy)
            event_type = _event_type(alert.alert_type)
            audit_id = await AuditService().record(
                self._session,
                AuditEvent(
                    actor_user_id=metadata.actor_id,
                    company_id=alert.company_id,
                    branch_id=None,
                    module="finance",
                    entity_type="cash_flow_alert",
                    entity_id=alert.id,
                    operation=event_type,
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                    after_snapshot=snapshot,
                    occurred_at=metadata.detected_at,
                    source_ip=metadata.source_ip,
                ),
            )
            envelope = MessageEnvelope.new(
                message_kind=MessageKind.DOMAIN_EVENT,
                message_type=event_type,
                event_version=1,
                producer_module="finance",
                producer_domain="cash_flow",
                aggregate_type="cash_flow_alert",
                aggregate_id=alert.id,
                aggregate_version=1,
                company_id=alert.company_id,
                branch_id=None,
                correlation_id=metadata.correlation_id,
                causation_id=None,
                request_id=metadata.request_id,
                payload=snapshot,
            )
            await OutboxService().enqueue(self._session, envelope)
            results.append(CashFlowAlertRecordResult(alert, audit_id, envelope.message_id))
        return tuple(results)

    async def _insert(
        self,
        alert: CashFlowRiskAlert,
        *,
        policy: CashFlowAlertPolicy,
        metadata: CashFlowAlertMetadata,
    ) -> bool:
        statement = (
            insert(CashFlowAlertModel)
            .values(
                id=alert.id,
                company_id=alert.company_id,
                projection_id=alert.projection_id,
                projection_version=alert.projection_version,
                source=alert.source.value,
                alert_type=alert.alert_type.value,
                severity=alert.severity.value,
                dimension=alert.dimension.value,
                subject_key=alert.subject_key,
                breach_on=alert.breach_on,
                actual_value=alert.actual_value,
                threshold_value=alert.threshold_value,
                currency=alert.currency,
                policy_snapshot=policy.snapshot(),
                details=dict(alert.details),
                detected_at=metadata.detected_at,
                actor_id=metadata.actor_id,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
            )
            .on_conflict_do_nothing(index_elements=[CashFlowAlertModel.id])
            .returning(CashFlowAlertModel.id)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None


def _event_type(alert_type: CashFlowAlertType) -> str:
    if alert_type in {
        CashFlowAlertType.CASH_RUPTURE,
        CashFlowAlertType.SAFETY_THRESHOLD,
    }:
        return CASH_FLOW_LIQUIDITY_ALERT_TRIGGERED
    if alert_type is CashFlowAlertType.SCENARIO_SENSITIVITY:
        return CASH_FLOW_SENSITIVITY_ALERT_TRIGGERED
    return CASH_FLOW_CONCENTRATION_ALERT_TRIGGERED


def _snapshot(
    alert: CashFlowRiskAlert,
    policy: CashFlowAlertPolicy,
) -> dict[str, object]:
    return {
        "alert_id": str(alert.id),
        "company_id": str(alert.company_id),
        "projection_id": str(alert.projection_id),
        "projection_version": alert.projection_version,
        "source": alert.source.value,
        "alert_type": alert.alert_type.value,
        "severity": alert.severity.value,
        "dimension": alert.dimension.value,
        "subject_key": alert.subject_key,
        "breach_on": alert.breach_on.isoformat() if alert.breach_on is not None else None,
        "actual_value": str(alert.actual_value),
        "threshold_value": str(alert.threshold_value),
        "currency": alert.currency,
        "details": dict(alert.details),
        "policy": policy.snapshot(),
    }


__all__ = [
    "CASH_FLOW_CONCENTRATION_ALERT_TRIGGERED",
    "CASH_FLOW_LIQUIDITY_ALERT_TRIGGERED",
    "CASH_FLOW_SENSITIVITY_ALERT_TRIGGERED",
    "PostgresCashFlowAlertRecorder",
]

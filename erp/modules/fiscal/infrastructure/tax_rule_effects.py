"""PostgreSQL Audit/Outbox adapter for M11 tax-rule mutations."""

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.fiscal.application.tax_rules import TaxRuleCommandMetadata
from erp.modules.fiscal.domain import TaxRule
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class _AuditWriter(Protocol):
    async def record(self, session: AsyncSession, event: AuditEvent) -> UUID: ...


class _OutboxWriter(Protocol):
    async def enqueue(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
        *,
        headers: dict[str, Any] | None = None,
    ) -> UUID: ...


class PostgresTaxRuleEffects:
    """Stage tax-rule audit and event records in the caller-owned transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: _AuditWriter | None = None,
        outbox: _OutboxWriter | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService()
        self._outbox = outbox or OutboxService()

    async def record(
        self,
        *,
        before: TaxRule,
        after: TaxRule,
        event_type: str,
        actor_id: UUID,
        metadata: TaxRuleCommandMetadata,
    ) -> tuple[UUID, UUID]:
        audit_id = await self._audit.record(
            self._session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=after.company_id,
                branch_id=None,
                module="fiscal",
                entity_type="tax_rule",
                entity_id=after.id,
                operation=event_type,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=tax_rule_snapshot(before),
                after_snapshot=tax_rule_snapshot(after),
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event_type,
            event_version=1,
            producer_module="fiscal",
            producer_domain="fiscal",
            aggregate_type="tax_rule",
            aggregate_id=after.id,
            aggregate_version=after.version,
            company_id=after.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload=tax_rule_snapshot(after),
        )
        await self._outbox.enqueue(self._session, envelope)
        return envelope.message_id, audit_id


def tax_rule_snapshot(rule: TaxRule) -> dict[str, object]:
    return {
        "id": str(rule.id),
        "company_id": str(rule.company_id),
        "code": rule.code,
        "version_code": rule.version_code,
        "flow": rule.criteria.flow.value,
        "ncm": rule.criteria.ncm,
        "cfop": rule.criteria.cfop,
        "rates": {
            "icms": str(rule.rates.icms),
            "pis": str(rule.rates.pis),
            "cofins": str(rule.rates.cofins),
            "ipi": str(rule.rates.ipi),
        },
        "status": rule.status.value,
        "effective_from": rule.effective_from.isoformat(),
        "effective_until": (
            None if rule.effective_until is None else rule.effective_until.isoformat()
        ),
        "created_by": str(rule.created_by),
        "activated_by": None if rule.activated_by is None else str(rule.activated_by),
        "activated_at": (None if rule.activated_at is None else rule.activated_at.isoformat()),
        "retired_at": None if rule.retired_at is None else rule.retired_at.isoformat(),
        "version": rule.version,
    }


__all__ = ["PostgresTaxRuleEffects", "tax_rule_snapshot"]

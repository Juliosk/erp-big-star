"""Framework-neutral application service for governed M11 tax rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from erp.modules.fiscal.domain import TaxRule, TaxRuleVersionConflictError
from erp.platform.errors import ApplicationError

TAX_RULE_ACTIVATED = "TaxRuleActivated"
TAX_RULE_RETIRED = "TaxRuleRetired"


@dataclass(frozen=True, slots=True)
class TaxRuleCommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None

    @classmethod
    def new(cls) -> TaxRuleCommandMetadata:
        return cls(uuid4(), uuid4())


@dataclass(frozen=True, slots=True)
class ChangeTaxRule:
    company_id: UUID
    tax_rule_id: UUID
    expected_version: int
    occurred_at: datetime
    metadata: TaxRuleCommandMetadata = field(default_factory=TaxRuleCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class TaxRuleMutationResult:
    rule: TaxRule
    event_id: UUID
    audit_id: UUID


class TaxRuleStore(Protocol):
    async def get_for_update(self, rule_id: UUID) -> TaxRule | None: ...

    async def save(
        self,
        rule: TaxRule,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> TaxRule: ...


class TaxRuleEffectsPort(Protocol):
    async def record(
        self,
        *,
        before: TaxRule,
        after: TaxRule,
        event_type: str,
        actor_id: UUID,
        metadata: TaxRuleCommandMetadata,
    ) -> tuple[UUID, UUID]: ...


class TaxRuleApplicationService:
    """Apply maker-checker tax-rule transitions inside one caller transaction."""

    def __init__(self, repository: TaxRuleStore, effects: TaxRuleEffectsPort) -> None:
        self._repository = repository
        self._effects = effects

    async def activate(
        self,
        command: ChangeTaxRule,
        *,
        actor_id: UUID,
    ) -> TaxRuleMutationResult:
        current = await self._load(command)
        activated = current.activate(actor_id=actor_id, occurred_at=command.occurred_at)
        return await self._persist(
            current,
            activated,
            actor_id=actor_id,
            event_type=TAX_RULE_ACTIVATED,
            metadata=command.metadata,
        )

    async def retire(
        self,
        command: ChangeTaxRule,
        *,
        actor_id: UUID,
    ) -> TaxRuleMutationResult:
        current = await self._load(command)
        retired = current.retire(occurred_at=command.occurred_at)
        return await self._persist(
            current,
            retired,
            actor_id=actor_id,
            event_type=TAX_RULE_RETIRED,
            metadata=command.metadata,
        )

    async def _load(self, command: ChangeTaxRule) -> TaxRule:
        _validate_change(command)
        current = await self._repository.get_for_update(command.tax_rule_id)
        if current is None or current.company_id != command.company_id:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Tax rule not found.",
                status_code=404,
            )
        if current.version != command.expected_version:
            raise TaxRuleVersionConflictError(
                f"Tax rule expected version {command.expected_version} is stale."
            )
        return current

    async def _persist(
        self,
        before: TaxRule,
        after: TaxRule,
        *,
        actor_id: UUID,
        event_type: str,
        metadata: TaxRuleCommandMetadata,
    ) -> TaxRuleMutationResult:
        saved = await self._repository.save(
            after,
            actor_id=actor_id,
            expected_version=before.version,
        )
        event_id, audit_id = await self._effects.record(
            before=before,
            after=saved,
            event_type=event_type,
            actor_id=actor_id,
            metadata=metadata,
        )
        return TaxRuleMutationResult(saved, event_id, audit_id)


def _validate_change(command: ChangeTaxRule) -> None:
    if not isinstance(command, ChangeTaxRule):
        raise TypeError("command must be a ChangeTaxRule.")
    for value, field_name in (
        (command.company_id, "company_id"),
        (command.tax_rule_id, "tax_rule_id"),
    ):
        if not isinstance(value, UUID) or value.int == 0:
            raise ValueError(f"{field_name} must be a non-zero UUID.")
    if (
        not isinstance(command.expected_version, int)
        or isinstance(command.expected_version, bool)
        or command.expected_version < 1
    ):
        raise ValueError("expected_version must be a positive integer.")
    if not isinstance(command.occurred_at, datetime) or command.occurred_at.tzinfo is None:
        raise ValueError("occurred_at must be timezone-aware.")


__all__ = [
    "TAX_RULE_ACTIVATED",
    "TAX_RULE_RETIRED",
    "ChangeTaxRule",
    "TaxRuleApplicationService",
    "TaxRuleCommandMetadata",
    "TaxRuleEffectsPort",
    "TaxRuleMutationResult",
    "TaxRuleStore",
]

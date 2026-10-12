"""Infrastructure port used to compose M12 with M22 without domain coupling."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import Payable


@dataclass(frozen=True, slots=True)
class PayableApprovalPlan:
    workflow_instance_id: UUID | None
    authority_limit: Decimal | None
    sod_threshold: Decimal


class PayableApprovalGateway(Protocol):
    async def plan(
        self,
        session: AsyncSession,
        *,
        payable: Payable,
        actor_id: UUID,
        granted_permissions: frozenset[str],
    ) -> PayableApprovalPlan: ...


class OutboxOnlyApprovalGateway:
    """Compatibility fallback: always requires an external M22 decision."""

    async def plan(
        self,
        session: AsyncSession,
        *,
        payable: Payable,
        actor_id: UUID,
        granted_permissions: frozenset[str],
    ) -> PayableApprovalPlan:
        del session, payable, actor_id, granted_permissions
        return PayableApprovalPlan(uuid4(), Decimal("0.00"), Decimal("0.01"))


__all__ = [
    "OutboxOnlyApprovalGateway",
    "PayableApprovalGateway",
    "PayableApprovalPlan",
]

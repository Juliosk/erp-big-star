"""Tenant-bound repository for payable governance facts."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import PayableApprovalStatus, PayableGovernance
from erp.modules.finance.infrastructure.payable_governance_model import PayableGovernanceModel
from erp.platform.concurrency import OptimisticLockError


class PayableGovernanceRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        self._session = session
        self._company_id = company_id

    async def get(self, payable_id: UUID, *, for_update: bool = False) -> PayableGovernance | None:
        statement = select(PayableGovernanceModel).where(
            PayableGovernanceModel.company_id == self._company_id,
            PayableGovernanceModel.payable_id == payable_id,
        )
        if for_update:
            statement = statement.with_for_update()
        model = (await self._session.scalars(statement)).one_or_none()
        return None if model is None else _domain(model)

    async def get_or_create(self, payable_id: UUID, *, actor_id: UUID) -> PayableGovernance:
        current = await self.get(payable_id, for_update=True)
        if current is not None:
            return current
        value = PayableGovernance(company_id=self._company_id, payable_id=payable_id)
        self._session.add(
            PayableGovernanceModel(
                company_id=value.company_id,
                payable_id=value.payable_id,
                fiscal_blocked=value.fiscal_blocked,
                purchasing_blocked=value.purchasing_blocked,
                approval_status=value.approval_status,
                workflow_instance_id=None,
                authority_limit=None,
                sod_threshold=value.sod_threshold,
                version=value.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._session.flush()
        return value

    async def save(
        self, value: PayableGovernance, *, actor_id: UUID, expected_version: int
    ) -> PayableGovernance:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(PayableGovernanceModel)
                .where(
                    PayableGovernanceModel.company_id == self._company_id,
                    PayableGovernanceModel.payable_id == value.payable_id,
                    PayableGovernanceModel.version == expected_version,
                )
                .values(
                    fiscal_blocked=value.fiscal_blocked,
                    purchasing_blocked=value.purchasing_blocked,
                    approval_status=value.approval_status,
                    workflow_instance_id=value.workflow_instance_id,
                    authority_limit=value.authority_limit,
                    sod_threshold=value.sod_threshold,
                    version=value.version,
                    updated_by=actor_id,
                    updated_at=func.now(),
                )
            ),
        )
        if result.rowcount != 1:
            raise OptimisticLockError(expected_version=expected_version)
        await self._session.flush()
        return value


def _domain(model: PayableGovernanceModel) -> PayableGovernance:
    return PayableGovernance(
        company_id=model.company_id,
        payable_id=model.payable_id,
        fiscal_blocked=model.fiscal_blocked,
        purchasing_blocked=model.purchasing_blocked,
        approval_status=PayableApprovalStatus(model.approval_status),
        workflow_instance_id=model.workflow_instance_id,
        authority_limit=model.authority_limit,
        sod_threshold=model.sod_threshold,
        version=model.version,
    )


__all__ = ["PayableGovernanceRepository"]

"""Composition adapter connecting M15's public port to M22's application service."""

from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application import DiscountWorkflowGateway
from erp.modules.workflow.application import OpenWorkflowInstance, WorkflowInstanceService


class WorkflowDiscountGateway(DiscountWorkflowGateway):
    def __init__(self, workflows: WorkflowInstanceService) -> None:
        self._workflows = workflows

    async def open(
        self,
        context: SecurityContext,
        *,
        company_id: UUID,
        quote_id: UUID,
        source_fingerprint: str,
    ) -> UUID:
        detail = await self._workflows.open_instance(
            context,
            OpenWorkflowInstance(
                company_id=company_id,
                source_module="SALES",
                source_type="QUOTE_DISCOUNT",
                source_id=quote_id,
                source_fingerprint=source_fingerprint,
            ),
        )
        return detail.instance.id


__all__ = ["WorkflowDiscountGateway"]

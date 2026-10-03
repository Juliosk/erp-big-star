"""Authorized M6 purchase requisition and purchase order use cases."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.application.permissions import (
    PROCUREMENT_ORDER_MANAGE,
    PROCUREMENT_ORDER_READ,
    PROCUREMENT_REQUISITION_MANAGE,
    PROCUREMENT_REQUISITION_READ,
    ProcurementAuthorization,
)
from erp.modules.procurement.domain import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequisition,
    RequisitionStatus,
    RequisitionUrgency,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class RequisitionLineInput:
    product_id: UUID
    quantity: Decimal
    unit_of_measure: str
    needed_by: date
    urgency: RequisitionUrgency
    specification: str


@dataclass(frozen=True, slots=True)
class CreateRequisition:
    company_id: UUID
    number: str
    cost_center_id: UUID
    justification: str
    lines: tuple[RequisitionLineInput, ...]


@dataclass(frozen=True, slots=True)
class ProcurementCommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None

    @classmethod
    def new(cls) -> ProcurementCommandMetadata:
        return cls(uuid4(), uuid4())


class RequisitionAction(StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CANCEL = "CANCEL"


@dataclass(frozen=True, slots=True)
class ChangeRequisitionStatus:
    company_id: UUID
    requisition_id: UUID
    expected_version: int
    action: RequisitionAction
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class PurchaseOrderLineInput:
    requisition_item_id: UUID
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class CreatePurchaseOrder:
    company_id: UUID
    number: str
    source_requisition_id: UUID
    supplier_id: UUID
    currency: str
    payment_terms_code: str
    payment_terms_description: str
    installment_days: tuple[int, ...]
    lines: tuple[PurchaseOrderLineInput, ...]


class PurchaseOrderAction(StrEnum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    ISSUE = "ISSUE"
    CANCEL = "CANCEL"


@dataclass(frozen=True, slots=True)
class ChangePurchaseOrderStatus:
    company_id: UUID
    purchase_order_id: UUID
    expected_version: int
    action: PurchaseOrderAction
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class ReceivePurchaseOrder:
    company_id: UUID
    purchase_order_id: UUID
    expected_version: int
    receipts: tuple[tuple[UUID, Decimal], ...]
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class RequisitionPage:
    items: tuple[PurchaseRequisition, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class PurchaseOrderPage:
    items: tuple[PurchaseOrder, ...]
    page: int
    page_size: int
    has_more: bool


class PurchasingStore(Protocol):
    async def create_requisition(
        self, requisition: PurchaseRequisition, *, actor_id: UUID
    ) -> PurchaseRequisition: ...
    async def change_requisition(
        self, command: ChangeRequisitionStatus, *, actor_id: UUID
    ) -> PurchaseRequisition: ...
    async def get_requisition(
        self, company_id: UUID, requisition_id: UUID
    ) -> PurchaseRequisition | None: ...
    async def list_requisitions(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: RequisitionStatus | None,
        cost_center_id: UUID | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> RequisitionPage: ...
    async def create_order(
        self, command: CreatePurchaseOrder, *, actor_id: UUID
    ) -> PurchaseOrder: ...
    async def change_order(
        self, command: ChangePurchaseOrderStatus, *, actor_id: UUID
    ) -> PurchaseOrder: ...
    async def receive_order(
        self, command: ReceivePurchaseOrder, *, actor_id: UUID
    ) -> PurchaseOrder: ...
    async def get_order(self, company_id: UUID, order_id: UUID) -> PurchaseOrder | None: ...
    async def list_orders(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PurchaseOrderStatus | None,
        supplier_id: UUID | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> PurchaseOrderPage: ...


class PurchasingService:
    def __init__(self, store: PurchasingStore, authorization: ProcurementAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create_requisition(
        self, context: SecurityContext, command: CreateRequisition
    ) -> PurchaseRequisition:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_REQUISITION_MANAGE, write=True
        )
        try:
            requisition = PurchaseRequisition.create(
                company_id=command.company_id,
                number=command.number,
                requester_id=context.principal.user_id,
                cost_center_id=command.cost_center_id,
                justification=command.justification,
                lines=tuple(
                    (
                        line.product_id,
                        line.quantity,
                        line.unit_of_measure,
                        line.needed_by,
                        line.urgency,
                        line.specification,
                    )
                    for line in command.lines
                ),
            )
        except ValueError as error:
            raise _validation("Invalid purchase requisition.", error) from error
        return await self._store.create_requisition(requisition, actor_id=context.principal.user_id)

    async def change_requisition(
        self, context: SecurityContext, command: ChangeRequisitionStatus
    ) -> PurchaseRequisition:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_REQUISITION_MANAGE, write=True
        )
        return await self._store.change_requisition(command, actor_id=context.principal.user_id)

    async def get_requisition(
        self, context: SecurityContext, company_id: UUID, requisition_id: UUID
    ) -> PurchaseRequisition:
        await self._authorization.require(context, company_id, PROCUREMENT_REQUISITION_READ)
        value = await self._store.get_requisition(company_id, requisition_id)
        if value is None:
            raise _not_found("Purchase requisition")
        return value

    async def list_requisitions(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: RequisitionStatus | None,
        cost_center_id: UUID | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> RequisitionPage:
        await self._authorization.require(context, company_id, PROCUREMENT_REQUISITION_READ)
        filters = {
            "page": page,
            "page_size": page_size,
            "created_from": created_from,
            "created_to": created_to,
        }
        _validate_filters(filters)
        return await self._store.list_requisitions(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            cost_center_id=cost_center_id,
            created_from=created_from,
            created_to=created_to,
        )

    async def create_order(
        self, context: SecurityContext, command: CreatePurchaseOrder
    ) -> PurchaseOrder:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_ORDER_MANAGE, write=True
        )
        return await self._store.create_order(command, actor_id=context.principal.user_id)

    async def change_order(
        self, context: SecurityContext, command: ChangePurchaseOrderStatus
    ) -> PurchaseOrder:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_ORDER_MANAGE, write=True
        )
        return await self._store.change_order(command, actor_id=context.principal.user_id)

    async def receive_order(
        self, context: SecurityContext, command: ReceivePurchaseOrder
    ) -> PurchaseOrder:
        await self._authorization.require(
            context, command.company_id, PROCUREMENT_ORDER_MANAGE, write=True
        )
        return await self._store.receive_order(command, actor_id=context.principal.user_id)

    async def get_order(
        self, context: SecurityContext, company_id: UUID, order_id: UUID
    ) -> PurchaseOrder:
        await self._authorization.require(context, company_id, PROCUREMENT_ORDER_READ)
        value = await self._store.get_order(company_id, order_id)
        if value is None:
            raise _not_found("Purchase order")
        return value

    async def list_orders(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: PurchaseOrderStatus | None,
        supplier_id: UUID | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> PurchaseOrderPage:
        await self._authorization.require(context, company_id, PROCUREMENT_ORDER_READ)
        filters = {
            "page": page,
            "page_size": page_size,
            "created_from": created_from,
            "created_to": created_to,
        }
        _validate_filters(filters)
        return await self._store.list_orders(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            supplier_id=supplier_id,
            created_from=created_from,
            created_to=created_to,
        )


def _validate_filters(filters: Mapping[str, object]) -> None:
    page, page_size = filters.get("page"), filters.get("page_size")
    if (
        type(page) is not int
        or not 1 <= page <= 100_000
        or type(page_size) is not int
        or not 1 <= page_size <= 100
    ):
        raise ApplicationError(
            code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
        )
    start, end = filters.get("created_from"), filters.get("created_to")
    if start is not None and end is not None and start > end:  # type: ignore[operator]
        raise ApplicationError(
            code="VALIDATION_ERROR",
            message="created_from must not exceed created_to.",
            status_code=422,
        )


def _validation(message: str, error: ValueError) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message=message,
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message=f"{resource} not found.", status_code=404
    )


def enforce_separation_of_duties(*, owner_id: UUID, approver_id: UUID) -> None:
    if owner_id == approver_id:
        raise ApplicationError(
            code="SOD_VIOLATION",
            message="The requester or buyer cannot approve their own purchase.",
            status_code=403,
        )


__all__ = [name for name in globals() if not name.startswith("_")]

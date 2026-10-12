"""Transactional PostgreSQL adapter for M6 purchasing use cases."""

from datetime import datetime
from uuid import UUID

from erp.modules.procurement.application.purchasing import (
    ChangePurchaseOrderStatus,
    ChangeRequisitionStatus,
    CreatePurchaseOrder,
    PurchaseOrderAction,
    PurchaseOrderPage,
    ReceivePurchaseOrder,
    RequisitionAction,
    RequisitionPage,
    enforce_separation_of_duties,
)
from erp.modules.procurement.domain import (
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequisition,
    RequisitionStatus,
    SupplierStatus,
)
from erp.modules.procurement.infrastructure.purchasing_effects import (
    PURCHASE_APPROVAL_REQUESTED,
    PURCHASE_ORDER_APPROVED,
    PURCHASE_ORDER_CANCELLED,
    record_purchasing_effect,
)
from erp.modules.procurement.infrastructure.purchasing_repository import (
    PurchaseOrderRepository,
    PurchaseRequisitionRepository,
)
from erp.modules.procurement.infrastructure.supplier_repository import SupplierRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail


class PostgresPurchasingStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_requisition(
        self, requisition: PurchaseRequisition, *, actor_id: UUID
    ) -> PurchaseRequisition:
        async with self._database.session() as session, session.begin():
            await PurchaseRequisitionRepository(session, company_id=requisition.company_id).add(
                requisition, actor_id=actor_id
            )
            return requisition

    async def change_requisition(
        self, command: ChangeRequisitionStatus, *, actor_id: UUID
    ) -> PurchaseRequisition:
        async with self._database.session() as session, session.begin():
            repository = PurchaseRequisitionRepository(session, company_id=command.company_id)
            current = await repository.get(command.requisition_id)
            if current is None:
                raise _not_found("Purchase requisition")
            _version(current.version, command.expected_version)
            if command.action is RequisitionAction.APPROVE and current.requester_id == actor_id:
                enforce_separation_of_duties(owner_id=current.requester_id, approver_id=actor_id)
            try:
                changed = {
                    RequisitionAction.SUBMIT: current.submit,
                    RequisitionAction.APPROVE: current.approve,
                    RequisitionAction.REJECT: current.reject,
                    RequisitionAction.CANCEL: current.cancel,
                }[command.action]()
            except ValueError as error:
                raise _validation("Invalid requisition transition.", error) from error
            changed = await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            event_type = (
                PURCHASE_APPROVAL_REQUESTED
                if command.action is RequisitionAction.SUBMIT
                else {
                    RequisitionAction.APPROVE: "PurchaseRequisitionApproved",
                    RequisitionAction.REJECT: "PurchaseRequisitionRejected",
                    RequisitionAction.CANCEL: "PurchaseRequisitionCancelled",
                }[command.action]
            )
            await record_purchasing_effect(
                session,
                before=current,
                after=changed,
                event_type=event_type,
                actor_id=actor_id,
                metadata=command.metadata,
            )
            return changed

    async def get_requisition(
        self, company_id: UUID, requisition_id: UUID
    ) -> PurchaseRequisition | None:
        async with self._database.session() as session:
            return await PurchaseRequisitionRepository(session, company_id=company_id).get(
                requisition_id
            )

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
    ) -> RequisitionPage:
        async with self._database.session() as session:
            repository = PurchaseRequisitionRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            values = await repository.list(
                status=status,
                cost_center_id=cost_center_id,
                created_from=created_from,
                created_to=created_to,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                cost_center_id=cost_center_id,
                created_from=created_from,
                created_to=created_to,
                limit=1,
                offset=offset + page_size,
            )
            return RequisitionPage(values, page, page_size, bool(more))

    async def create_order(self, command: CreatePurchaseOrder, *, actor_id: UUID) -> PurchaseOrder:
        async with self._database.session() as session, session.begin():
            requisitions = PurchaseRequisitionRepository(session, company_id=command.company_id)
            requisition = await requisitions.get(command.source_requisition_id)
            if requisition is None:
                raise _not_found("Purchase requisition")
            if requisition.status is not RequisitionStatus.APPROVED:
                raise ApplicationError(
                    code="BUSINESS_VALIDATION_ERROR",
                    message="Only approved requisitions can originate purchase orders.",
                    status_code=422,
                )
            supplier = await SupplierRepository(session, company_id=command.company_id).get(
                command.supplier_id
            )
            if supplier is None:
                raise _not_found("Supplier")
            if supplier.status is not SupplierStatus.ACTIVE:
                raise ApplicationError(
                    code="BUSINESS_VALIDATION_ERROR",
                    message="Supplier must be active.",
                    status_code=422,
                )
            requisition_items = {item.id: item for item in requisition.items}
            if not command.lines or len(
                {line.requisition_item_id for line in command.lines}
            ) != len(command.lines):
                raise ApplicationError(
                    code="BUSINESS_VALIDATION_ERROR",
                    message="Purchase order lines must be unique and non-empty.",
                    status_code=422,
                )
            try:
                lines = tuple(
                    (
                        line.requisition_item_id,
                        requisition_items[line.requisition_item_id].product_id,
                        line.quantity,
                        line.unit_price,
                        command.currency,
                    )
                    for line in command.lines
                )
                if any(
                    line.quantity > requisition_items[line.requisition_item_id].quantity
                    for line in command.lines
                ):
                    raise ValueError("purchase order quantity cannot exceed requisition quantity.")
                order = PurchaseOrder.create_from_requisition(
                    company_id=command.company_id,
                    number=command.number,
                    supplier_id=command.supplier_id,
                    source_requisition_id=requisition.id,
                    buyer_id=actor_id,
                    currency_code=command.currency,
                    payment_terms=PaymentTerms.create(
                        code=command.payment_terms_code,
                        description=command.payment_terms_description,
                        installment_days=command.installment_days,
                    ),
                    lines=lines,
                )
            except KeyError as error:
                raise ApplicationError(
                    code="BUSINESS_VALIDATION_ERROR",
                    message="A purchase order line is outside the source requisition.",
                    status_code=422,
                ) from error
            except ValueError as error:
                raise _validation("Invalid purchase order.", error) from error
            await PurchaseOrderRepository(session, company_id=command.company_id).add(
                order, actor_id=actor_id
            )
            return order

    async def change_order(
        self, command: ChangePurchaseOrderStatus, *, actor_id: UUID
    ) -> PurchaseOrder:
        async with self._database.session() as session, session.begin():
            repository = PurchaseOrderRepository(session, company_id=command.company_id)
            current = await repository.get(command.purchase_order_id)
            if current is None:
                raise _not_found("Purchase order")
            _version(current.version, command.expected_version)
            if command.action is PurchaseOrderAction.APPROVE and current.buyer_id == actor_id:
                enforce_separation_of_duties(owner_id=current.buyer_id, approver_id=actor_id)
            try:
                changed = {
                    PurchaseOrderAction.SUBMIT: current.submit_for_approval,
                    PurchaseOrderAction.APPROVE: current.approve,
                    PurchaseOrderAction.ISSUE: current.issue,
                    PurchaseOrderAction.CANCEL: current.cancel,
                }[command.action]()
            except ValueError as error:
                raise _validation("Invalid purchase order transition.", error) from error
            changed = await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            event_type = {
                PurchaseOrderAction.SUBMIT: PURCHASE_APPROVAL_REQUESTED,
                PurchaseOrderAction.APPROVE: PURCHASE_ORDER_APPROVED,
                PurchaseOrderAction.ISSUE: "PurchaseOrderIssued",
                PurchaseOrderAction.CANCEL: PURCHASE_ORDER_CANCELLED,
            }[command.action]
            supplier_tax_id = None
            if event_type == PURCHASE_ORDER_APPROVED:
                supplier = await SupplierRepository(session, company_id=command.company_id).get(
                    current.supplier_id
                )
                if supplier is None:
                    raise _not_found("Supplier")
                supplier_tax_id = supplier.tax_identity.value
            await record_purchasing_effect(
                session,
                before=current,
                after=changed,
                event_type=event_type,
                actor_id=actor_id,
                metadata=command.metadata,
                supplier_tax_id=supplier_tax_id,
            )
            return changed

    async def receive_order(
        self, command: ReceivePurchaseOrder, *, actor_id: UUID
    ) -> PurchaseOrder:
        async with self._database.session() as session, session.begin():
            repository = PurchaseOrderRepository(session, company_id=command.company_id)
            current = await repository.get(command.purchase_order_id)
            if current is None:
                raise _not_found("Purchase order")
            _version(current.version, command.expected_version)
            try:
                changed = current.receive(command.receipts)
            except ValueError as error:
                raise _validation("Invalid purchase order receipt.", error) from error
            changed = await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            await record_purchasing_effect(
                session,
                before=current,
                after=changed,
                event_type="PurchaseOrderReceived",
                actor_id=actor_id,
                metadata=command.metadata,
            )
            return changed

    async def get_order(self, company_id: UUID, order_id: UUID) -> PurchaseOrder | None:
        async with self._database.session() as session:
            return await PurchaseOrderRepository(session, company_id=company_id).get(order_id)

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
    ) -> PurchaseOrderPage:
        async with self._database.session() as session:
            repository = PurchaseOrderRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            values = await repository.list(
                status=status,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
                limit=1,
                offset=offset + page_size,
            )
            return PurchaseOrderPage(values, page, page_size, bool(more))


def _version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The resource was changed by another transaction.",
            status_code=409,
        )


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message=f"{resource} not found.", status_code=404
    )


def _validation(message: str, error: ValueError) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message=message,
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = ["PostgresPurchasingStore"]

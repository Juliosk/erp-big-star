"""Official M6 purchase requisition and purchase order endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.api.purchasing_schemas import (
    CreatePurchaseOrderRequest,
    CreateRequisitionRequest,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    ReceivePurchaseOrderRequest,
    RequisitionListResponse,
    RequisitionResponse,
)
from erp.modules.procurement.api.routes import resolve_security_context
from erp.modules.procurement.api.versioning import require_version
from erp.modules.procurement.application.purchasing import (
    ChangePurchaseOrderStatus,
    ChangeRequisitionStatus,
    CreatePurchaseOrder,
    CreateRequisition,
    ProcurementCommandMetadata,
    PurchaseOrderAction,
    PurchaseOrderLineInput,
    PurchasingService,
    ReceivePurchaseOrder,
    RequisitionAction,
    RequisitionLineInput,
)
from erp.modules.procurement.domain import PurchaseOrderStatus, RequisitionStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/procurement", tags=["procurement-purchasing"])


def _metadata(request: Request) -> ProcurementCommandMetadata:
    return ProcurementCommandMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=request.client.host if request.client is not None else None,
    )


def get_purchasing_service(request: Request) -> PurchasingService:
    service = getattr(request.app.state, "procurement_purchasing", None)
    if not isinstance(service, PurchasingService):
        raise ApplicationError(
            code="PROCUREMENT_PURCHASING_UNAVAILABLE",
            message="Purchasing services unavailable.",
            status_code=503,
        )
    return service


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


@router.post("/requisitions", status_code=201, response_model=RequisitionResponse)
async def create_requisition(
    body: CreateRequisitionRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
) -> RequisitionResponse:
    value = await service.create_requisition(
        context,
        CreateRequisition(
            company_id=body.company_id,
            number=body.number,
            cost_center_id=body.cost_center_id,
            justification=body.justification,
            lines=tuple(RequisitionLineInput(**item.model_dump()) for item in body.items),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/procurement/requisitions/{value.id}?company_id={value.company_id}"
    )
    _etag(response, value.version)
    return RequisitionResponse.from_domain(value)


@router.get("/requisitions", response_model=RequisitionListResponse)
async def list_requisitions(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: RequisitionStatus | None = None,
    cost_center_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> RequisitionListResponse:
    value = await service.list_requisitions(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        cost_center_id=cost_center_id,
        created_from=created_from,
        created_to=created_to,
    )
    response.headers["Cache-Control"] = "no-store"
    return RequisitionListResponse.from_page(value)


@router.get("/requisitions/{requisition_id}", response_model=RequisitionResponse)
async def get_requisition(
    requisition_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
) -> RequisitionResponse:
    value = await service.get_requisition(context, company_id, requisition_id)
    _etag(response, value.version)
    return RequisitionResponse.from_domain(value)


async def _change_requisition(
    requisition_id: UUID,
    company_id: UUID,
    action: RequisitionAction,
    response: Response,
    context: SecurityContext,
    service: PurchasingService,
    version: int,
    metadata: ProcurementCommandMetadata,
) -> RequisitionResponse:
    value = await service.change_requisition(
        context, ChangeRequisitionStatus(company_id, requisition_id, version, action, metadata)
    )
    _etag(response, value.version)
    return RequisitionResponse.from_domain(value)


def _requisition_action(path: str, action: RequisitionAction) -> None:
    async def endpoint(
        requisition_id: UUID,
        company_id: UUID,
        request: Request,
        response: Response,
        context: Annotated[SecurityContext, Depends(resolve_security_context)],
        service: Annotated[PurchasingService, Depends(get_purchasing_service)],
        version: Annotated[int, Depends(require_version)],
    ) -> RequisitionResponse:
        return await _change_requisition(
            requisition_id,
            company_id,
            action,
            response,
            context,
            service,
            version,
            _metadata(request),
        )

    router.add_api_route(
        f"/requisitions/{{requisition_id}}/{path}",
        endpoint,
        methods=["POST"],
        response_model=RequisitionResponse,
        name=f"{path}_purchase_requisition",
    )


for _requisition_path, _requisition_action_value in (
    ("submit", RequisitionAction.SUBMIT),
    ("approve", RequisitionAction.APPROVE),
    ("reject", RequisitionAction.REJECT),
    ("cancel", RequisitionAction.CANCEL),
):
    _requisition_action(_requisition_path, _requisition_action_value)


@router.post("/purchase-orders", status_code=201, response_model=PurchaseOrderResponse)
async def create_purchase_order(
    body: CreatePurchaseOrderRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
) -> PurchaseOrderResponse:
    value = await service.create_order(
        context,
        CreatePurchaseOrder(
            company_id=body.company_id,
            number=body.number,
            source_requisition_id=body.source_requisition_id,
            supplier_id=body.supplier_id,
            currency=body.currency,
            payment_terms_code=body.payment_terms_code,
            payment_terms_description=body.payment_terms_description,
            installment_days=tuple(body.installment_days),
            lines=tuple(PurchaseOrderLineInput(**item.model_dump()) for item in body.items),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/procurement/purchase-orders/{value.id}?company_id={value.company_id}"
    )
    _etag(response, value.version)
    return PurchaseOrderResponse.from_domain(value)


@router.get("/purchase-orders", response_model=PurchaseOrderListResponse)
async def list_purchase_orders(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: PurchaseOrderStatus | None = None,
    supplier_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> PurchaseOrderListResponse:
    value = await service.list_orders(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        supplier_id=supplier_id,
        created_from=created_from,
        created_to=created_to,
    )
    response.headers["Cache-Control"] = "no-store"
    return PurchaseOrderListResponse.from_page(value)


@router.get("/purchase-orders/{order_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    order_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
) -> PurchaseOrderResponse:
    value = await service.get_order(context, company_id, order_id)
    _etag(response, value.version)
    return PurchaseOrderResponse.from_domain(value)


async def _change_order(
    order_id: UUID,
    company_id: UUID,
    action: PurchaseOrderAction,
    response: Response,
    context: SecurityContext,
    service: PurchasingService,
    version: int,
    metadata: ProcurementCommandMetadata,
) -> PurchaseOrderResponse:
    value = await service.change_order(
        context, ChangePurchaseOrderStatus(company_id, order_id, version, action, metadata)
    )
    _etag(response, value.version)
    return PurchaseOrderResponse.from_domain(value)


def _order_action(path: str, action: PurchaseOrderAction) -> None:
    async def endpoint(
        order_id: UUID,
        company_id: UUID,
        request: Request,
        response: Response,
        context: Annotated[SecurityContext, Depends(resolve_security_context)],
        service: Annotated[PurchasingService, Depends(get_purchasing_service)],
        version: Annotated[int, Depends(require_version)],
    ) -> PurchaseOrderResponse:
        return await _change_order(
            order_id,
            company_id,
            action,
            response,
            context,
            service,
            version,
            _metadata(request),
        )

    router.add_api_route(
        f"/purchase-orders/{{order_id}}/{path}",
        endpoint,
        methods=["POST"],
        response_model=PurchaseOrderResponse,
        name=f"{path}_purchase_order",
    )


for _order_path, _order_action_value in (
    ("submit", PurchaseOrderAction.SUBMIT),
    ("approve", PurchaseOrderAction.APPROVE),
    ("issue", PurchaseOrderAction.ISSUE),
    ("cancel", PurchaseOrderAction.CANCEL),
):
    _order_action(_order_path, _order_action_value)


@router.post("/purchase-orders/{order_id}/receive", response_model=PurchaseOrderResponse)
async def receive_purchase_order(
    order_id: UUID,
    company_id: UUID,
    body: ReceivePurchaseOrderRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PurchasingService, Depends(get_purchasing_service)],
    version: Annotated[int, Depends(require_version)],
) -> PurchaseOrderResponse:
    value = await service.receive_order(
        context,
        ReceivePurchaseOrder(
            company_id,
            order_id,
            version,
            tuple((item.item_id, item.quantity) for item in body.items),
            _metadata(request),
        ),
    )
    _etag(response, value.version)
    return PurchaseOrderResponse.from_domain(value)


__all__ = ["router"]

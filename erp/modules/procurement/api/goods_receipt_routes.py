"""Official REST endpoints for M6 physical goods receipts."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.api.goods_receipt_schemas import (
    CreateGoodsReceiptRequest,
    GoodsReceiptListResponse,
    GoodsReceiptResponse,
    InspectGoodsReceiptRequest,
    ReceiveGoodsReceiptRequest,
)
from erp.modules.procurement.api.routes import resolve_security_context
from erp.modules.procurement.api.versioning import require_version
from erp.modules.procurement.application.goods_receipts import (
    CreateGoodsReceipt,
    GoodsReceiptLineInput,
    GoodsReceiptService,
    InspectGoodsReceipt,
    InspectionDecisionInput,
    PostGoodsReceiptToInventory,
    ReceiveGoodsReceipt,
)
from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import GoodsReceiptStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/procurement/goods-receipts", tags=["procurement-goods-receipts"])


def get_goods_receipt_service(request: Request) -> GoodsReceiptService:
    service = getattr(request.app.state, "procurement_goods_receipts", None)
    if not isinstance(service, GoodsReceiptService):
        raise ApplicationError(
            code="PROCUREMENT_GOODS_RECEIPT_UNAVAILABLE",
            message="Goods receipt services unavailable.",
            status_code=503,
        )
    return service


def require_idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if value is None or not value.strip() or len(value) > 255:
        raise ApplicationError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="Idempotency-Key must contain between 1 and 255 characters.",
            status_code=400,
        )
    return value.strip()


def _metadata(request: Request) -> ProcurementCommandMetadata:
    return ProcurementCommandMetadata(
        request_id=UUID(request.state.request_id),
        correlation_id=UUID(request.state.correlation_id),
        source_ip=request.client.host if request.client is not None else None,
    )


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


@router.post("", status_code=201, response_model=GoodsReceiptResponse)
async def create_goods_receipt(
    body: CreateGoodsReceiptRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> GoodsReceiptResponse:
    value = await service.create(
        context,
        CreateGoodsReceipt(
            company_id=body.company_id,
            number=body.number,
            purchase_order_id=body.purchase_order_id,
            warehouse_id=body.warehouse_id,
            tolerance_percentage=body.tolerance_percentage,
            lines=tuple(GoodsReceiptLineInput(**item.model_dump()) for item in body.items),
            idempotency_key=idempotency_key,
            metadata=_metadata(request),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/procurement/goods-receipts/{value.id}?company_id={value.company_id}"
    )
    _etag(response, value.version)
    return GoodsReceiptResponse.from_domain(value)


@router.get("", response_model=GoodsReceiptListResponse)
async def list_goods_receipts(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    purchase_order_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status: GoodsReceiptStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> GoodsReceiptListResponse:
    value = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        purchase_order_id=purchase_order_id,
        supplier_id=supplier_id,
        status=status,
        created_from=created_from,
        created_to=created_to,
    )
    response.headers["Cache-Control"] = "no-store"
    return GoodsReceiptListResponse.from_page(value)


@router.get("/{receipt_id}", response_model=GoodsReceiptResponse)
async def get_goods_receipt(
    receipt_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)],
) -> GoodsReceiptResponse:
    value = await service.get(context, company_id, receipt_id)
    _etag(response, value.version)
    return GoodsReceiptResponse.from_domain(value)


@router.post("/{receipt_id}/receive", response_model=GoodsReceiptResponse)
async def receive_goods_receipt(
    receipt_id: UUID,
    company_id: UUID,
    body: ReceiveGoodsReceiptRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)],
    version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> GoodsReceiptResponse:
    value = await service.receive(
        context,
        ReceiveGoodsReceipt(
            company_id=company_id,
            receipt_id=receipt_id,
            expected_version=version,
            idempotency_key=idempotency_key,
            occurred_at=body.occurred_at,
            metadata=_metadata(request),
        ),
    )
    _etag(response, value.version)
    return GoodsReceiptResponse.from_domain(value)


@router.post("/{receipt_id}/inspect", response_model=GoodsReceiptResponse)
async def inspect_goods_receipt(
    receipt_id: UUID,
    company_id: UUID,
    body: InspectGoodsReceiptRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)],
    version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> GoodsReceiptResponse:
    value = await service.inspect(
        context,
        InspectGoodsReceipt(
            company_id=company_id,
            receipt_id=receipt_id,
            expected_version=version,
            decisions=tuple(
                InspectionDecisionInput(**decision.model_dump()) for decision in body.decisions
            ),
            idempotency_key=idempotency_key,
            metadata=_metadata(request),
        ),
    )
    _etag(response, value.version)
    return GoodsReceiptResponse.from_domain(value)


@router.post("/{receipt_id}/post-to-inventory", response_model=GoodsReceiptResponse)
async def post_goods_receipt_to_inventory(
    receipt_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[GoodsReceiptService, Depends(get_goods_receipt_service)],
    version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> GoodsReceiptResponse:
    value = await service.post_to_inventory(
        context,
        PostGoodsReceiptToInventory(
            company_id=company_id,
            receipt_id=receipt_id,
            expected_version=version,
            idempotency_key=idempotency_key,
            metadata=_metadata(request),
        ),
    )
    _etag(response, value.version)
    return GoodsReceiptResponse.from_domain(value)


__all__ = ["router"]

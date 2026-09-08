"""Public product responses, never ORM objects."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from erp.modules.product.domain import ProductLifecycle, ProductType


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    sku: str
    name: str
    product_type: ProductType
    uom: str
    lifecycle: ProductLifecycle
    version: int


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class ProductListResponse(BaseModel):
    data: list[ProductResponse]
    meta: PageMetadata


__all__ = ["PageMetadata", "ProductListResponse", "ProductResponse"]

"""Internal M2 persistence adapters, wired only at the composition boundary."""

from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.product.infrastructure.product_model import ProductModel
from erp.modules.product.infrastructure.product_repository import ProductRepository

__all__ = ["ProductBarcodeModel", "ProductModel", "ProductRepository"]

"""Company-owned product aggregate, independent of persistence and transport."""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4


class ProductType(StrEnum):
    """Official M2 material classifications."""

    PA = "PA"
    PI = "PI"
    MA = "MA"
    AUX = "AUX"
    EMB = "EMB"
    KIT = "KIT"


class ProductLifecycle(StrEnum):
    """M2 states; operational eligibility belongs to the consuming domain."""

    EM_DESENVOLVIMENTO = "EM_DESENVOLVIMENTO"
    EM_HOMOLOGACAO = "EM_HOMOLOGACAO"
    ATIVO = "ATIVO"
    FORA_DE_LINHA = "FORA_DE_LINHA"


def _identifier(value: str, *, field: str, maximum: int) -> None:
    if not 1 <= len(value) <= maximum or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*", value) is None:
        raise ValueError(f"{field} must be a canonical identifier of 1 to {maximum} characters.")


@dataclass(frozen=True, slots=True)
class Product:
    """One immutable snapshot; company and business keys are fixed in this slice."""

    id: UUID
    company_id: UUID
    code: str
    sku: str
    name: str
    product_type: ProductType
    uom: str
    lifecycle: ProductLifecycle
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise ValueError("Product identity and company scope must be UUIDs.")
        _identifier(self.code, field="code", maximum=64)
        _identifier(self.sku, field="sku", maximum=64)
        _identifier(self.uom, field="uom", maximum=12)
        if not 1 <= len(self.name) <= 200 or self.name != self.name.strip():
            raise ValueError("name must contain 1 to 200 trimmed characters.")
        if not isinstance(self.product_type, ProductType):
            raise ValueError("product_type must be an official M2 type.")
        if not isinstance(self.lifecycle, ProductLifecycle):
            raise ValueError("lifecycle must be an official M2 state.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        sku: str,
        name: str,
        product_type: ProductType,
        uom: str,
    ) -> Product:
        """New products always start in development at version one."""
        return cls(
            id=uuid4(),
            company_id=company_id,
            code=code.strip().upper(),
            sku=sku.strip().upper(),
            name=name.strip(),
            product_type=product_type,
            uom=uom.strip().upper(),
            lifecycle=ProductLifecycle.EM_DESENVOLVIMENTO,
            version=1,
        )

    def update_details(self, *, name: str, uom: str) -> Product:
        """Change descriptive master data, never identity, tenant or lifecycle."""
        candidate = replace(self, name=name.strip(), uom=uom.strip().upper())
        if candidate == self:
            return self
        return replace(candidate, version=self.version + 1)


__all__ = ["Product", "ProductLifecycle", "ProductType"]

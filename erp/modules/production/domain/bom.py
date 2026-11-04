"""Multilevel bill-of-materials rules and deterministic expansion."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from erp.modules.production.domain.exceptions import (
    BomCycleError,
    BomNotFoundError,
    InvalidProductionValueError,
    ProductionScopeError,
    UnitOfMeasureMismatchError,
)
from erp.modules.production.domain.values import (
    EngineeringVersion,
    ProductionQuantity,
    ScrapRate,
    require_uuid,
)


@dataclass(frozen=True, slots=True)
class BomItem:
    component_product_id: UUID
    quantity_per_output: ProductionQuantity
    scrap_rate: ScrapRate = field(default_factory=ScrapRate)

    def __post_init__(self) -> None:
        require_uuid(self.component_product_id, "component_product_id")
        if not isinstance(self.quantity_per_output, ProductionQuantity):
            raise InvalidProductionValueError(
                "quantity_per_output must be a ProductionQuantity."
            )
        if not isinstance(self.scrap_rate, ScrapRate):
            raise InvalidProductionValueError("scrap_rate must be a ScrapRate.")


@dataclass(frozen=True, slots=True)
class BillOfMaterials:
    company_id: UUID
    product_id: UUID
    version: EngineeringVersion
    output_quantity: ProductionQuantity
    items: tuple[BomItem, ...]
    record_version: int = 1

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.version, EngineeringVersion):
            raise InvalidProductionValueError("version must be an EngineeringVersion.")
        if not isinstance(self.output_quantity, ProductionQuantity):
            raise InvalidProductionValueError("output_quantity must be a ProductionQuantity.")
        if not isinstance(self.items, tuple) or not self.items:
            raise InvalidProductionValueError("items must be a non-empty tuple.")
        if any(not isinstance(item, BomItem) for item in self.items):
            raise InvalidProductionValueError("items must contain only BomItem values.")
        component_ids = tuple(item.component_product_id for item in self.items)
        if len(component_ids) != len(set(component_ids)):
            raise InvalidProductionValueError("component products must be unique inside a BOM.")
        if self.product_id in component_ids:
            raise BomCycleError("a BOM cannot consume its own product.")
        if type(self.record_version) is not int or self.record_version < 1:
            raise InvalidProductionValueError("record_version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class MaterialRequirement:
    product_id: UUID
    quantity: ProductionQuantity


@dataclass(frozen=True, slots=True)
class BomExpansionService:
    """Expands manufactured nodes and returns aggregated leaf requirements."""

    company_id: UUID
    boms: tuple[BillOfMaterials, ...]

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        if not isinstance(self.boms, tuple) or not self.boms:
            raise InvalidProductionValueError("boms must be a non-empty tuple.")
        if any(not isinstance(bom, BillOfMaterials) for bom in self.boms):
            raise InvalidProductionValueError("boms must contain only BillOfMaterials values.")
        if any(bom.company_id != self.company_id for bom in self.boms):
            raise ProductionScopeError("every BOM must belong to the expansion company.")
        product_ids = tuple(bom.product_id for bom in self.boms)
        if len(product_ids) != len(set(product_ids)):
            raise InvalidProductionValueError("only one BOM version can be active per product.")
        self._validate_acyclic()

    def expand(
        self,
        product_id: UUID,
        demanded_output: ProductionQuantity,
    ) -> tuple[MaterialRequirement, ...]:
        require_uuid(product_id, "product_id")
        if not isinstance(demanded_output, ProductionQuantity):
            raise InvalidProductionValueError(
                "demanded_output must be a ProductionQuantity."
            )
        catalogue = {bom.product_id: bom for bom in self.boms}
        if product_id not in catalogue:
            raise BomNotFoundError("no active BOM exists for the requested product.")

        leaves: dict[UUID, ProductionQuantity] = {}

        def visit(current_id: UUID, demand: ProductionQuantity) -> None:
            current = catalogue.get(current_id)
            if current is None:
                previous = leaves.get(current_id)
                if previous is None:
                    leaves[current_id] = demand
                    return
                if previous.unit is not demand.unit:
                    raise UnitOfMeasureMismatchError(
                        "one material cannot be aggregated with different units."
                    )
                leaves[current_id] = ProductionQuantity(
                    previous.amount + demand.amount,
                    demand.unit,
                )
                return
            if current.output_quantity.unit is not demand.unit:
                raise UnitOfMeasureMismatchError(
                    "demand unit must match the manufactured BOM output unit."
                )
            factor = demand.amount / current.output_quantity.amount
            for item in current.items:
                net = item.quantity_per_output.scaled_by(factor)
                visit(item.component_product_id, item.scrap_rate.gross_requirement(net))

        visit(product_id, demanded_output)
        return tuple(
            MaterialRequirement(product_id=leaf_id, quantity=quantity)
            for leaf_id, quantity in sorted(leaves.items(), key=lambda item: item[0].hex)
        )

    def _validate_acyclic(self) -> None:
        catalogue = {bom.product_id: bom for bom in self.boms}
        visited: set[UUID] = set()
        active: list[UUID] = []

        def visit(product_id: UUID) -> None:
            if product_id in active:
                cycle = [*active[active.index(product_id) :], product_id]
                path = " -> ".join(str(value) for value in cycle)
                raise BomCycleError(f"circular BOM structure detected: {path}.")
            if product_id in visited:
                return
            active.append(product_id)
            bom = catalogue[product_id]
            for item in bom.items:
                if item.component_product_id in catalogue:
                    visit(item.component_product_id)
            active.pop()
            visited.add(product_id)

        for product_id in catalogue:
            visit(product_id)


__all__ = [
    "BillOfMaterials",
    "BomExpansionService",
    "BomItem",
    "MaterialRequirement",
]


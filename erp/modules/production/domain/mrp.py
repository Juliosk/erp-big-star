"""Deterministic gross-to-net MRP calculation and planned-order generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from erp.modules.production.domain.bom import BillOfMaterials, BomExpansionService
from erp.modules.production.domain.exceptions import (
    BomNotFoundError,
    EngineeringUnavailableError,
    InvalidProductionValueError,
    MRPPolicyNotFoundError,
    ProductionScopeError,
    UnitOfMeasureMismatchError,
)
from erp.modules.production.domain.mrp_values import (
    MRPAlertKind,
    MRPDemand,
    MRPInventoryPosition,
    MRPNetRequirement,
    MRPPlan,
    MRPPlannedOrder,
    MRPPlannedOrderType,
    MRPPlanningAlert,
    MRPPlanningPolicy,
    MRPScheduledReceipt,
    MRPSupplyMode,
)
from erp.modules.production.domain.values import UnitOfMeasure, require_uuid


@dataclass(slots=True)
class _RequirementBucket:
    unit: UnitOfMeasure
    amount: Decimal = Decimal("0")
    source_ids: set[UUID] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class MRPEngine:
    """Calculate a reproducible, tenant-bound and time-phased supply plan."""

    company_id: UUID
    boms: tuple[BillOfMaterials, ...]
    policies: tuple[MRPPlanningPolicy, ...]

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        if not isinstance(self.boms, tuple) or any(
            not isinstance(bom, BillOfMaterials) for bom in self.boms
        ):
            raise InvalidProductionValueError(
                "boms must be a tuple of BillOfMaterials values."
            )
        if not isinstance(self.policies, tuple) or any(
            not isinstance(policy, MRPPlanningPolicy) for policy in self.policies
        ):
            raise InvalidProductionValueError(
                "policies must be a tuple of MRPPlanningPolicy values."
            )
        if any(bom.company_id != self.company_id for bom in self.boms) or any(
            policy.company_id != self.company_id for policy in self.policies
        ):
            raise ProductionScopeError("MRP inputs must belong to the engine company.")
        self._require_unique(
            tuple(bom.product_id for bom in self.boms),
            "only one active BOM is allowed per product",
        )
        self._require_unique(
            tuple(policy.product_id for policy in self.policies),
            "only one planning policy is allowed per product",
        )
        if self.boms:
            BomExpansionService(self.company_id, self.boms)

    def plan(
        self,
        *,
        as_of: date,
        demands: tuple[MRPDemand, ...],
        inventory: tuple[MRPInventoryPosition, ...] = (),
        scheduled_receipts: tuple[MRPScheduledReceipt, ...] = (),
    ) -> MRPPlan:
        self._date(as_of, "as_of")
        self._validate_inputs(demands, inventory, scheduled_receipts)
        gross: dict[UUID, dict[date, _RequirementBucket]] = {}
        for demand in demands:
            self._add_requirement(
                gross,
                product_id=demand.product_id,
                required_on=demand.required_on,
                unit=demand.quantity.unit,
                amount=demand.quantity.amount,
                source_id=demand.source_id,
            )

        bom_catalogue = {bom.product_id: bom for bom in self.boms}
        policy_catalogue = {policy.product_id: policy for policy in self.policies}
        inventory_catalogue = {position.product_id: position for position in inventory}
        receipt_catalogue = self._receipt_catalogue(scheduled_receipts)
        levels = self._low_level_codes(tuple(gross), bom_catalogue)
        requirements: list[MRPNetRequirement] = []
        planned_orders: list[MRPPlannedOrder] = []
        alerts: list[MRPPlanningAlert] = []

        for product_id in sorted(levels, key=lambda value: (levels[value], value.hex)):
            buckets = gross.get(product_id)
            if not buckets:
                continue
            available = self._initial_available(
                inventory_catalogue.get(product_id),
                next(iter(buckets.values())).unit,
            )
            receipts = receipt_catalogue.get(product_id, ())
            receipt_index = 0
            receipt_pool = Decimal("0")
            for required_on, bucket in sorted(buckets.items()):
                while (
                    receipt_index < len(receipts)
                    and receipts[receipt_index].available_on <= required_on
                ):
                    receipt = receipts[receipt_index]
                    self._require_unit(
                        receipt.quantity.unit,
                        bucket.unit,
                        "scheduled receipt",
                    )
                    receipt_pool += receipt.quantity.amount
                    receipt_index += 1
                line, order, alert = self._net_requirement(
                    as_of=as_of,
                    product_id=product_id,
                    required_on=required_on,
                    bucket=bucket,
                    available=available,
                    receipt_pool=receipt_pool,
                    policy=policy_catalogue.get(product_id),
                    order_sequence=len(planned_orders) + 1,
                )
                available = line.projected_available
                receipt_pool = Decimal("0")
                requirements.append(line)
                if order is None:
                    continue
                planned_orders.append(order)
                if alert is not None:
                    alerts.append(alert)
                if order.order_type is MRPPlannedOrderType.MANUFACTURE:
                    self._explode_planned_order(
                        order,
                        bom_catalogue,
                        gross,
                    )

        return MRPPlan(
            company_id=self.company_id,
            as_of=as_of,
            demands=tuple(
                sorted(
                    demands,
                    key=lambda value: (
                        value.required_on,
                        value.product_id.hex,
                        value.source_id.hex,
                    ),
                )
            ),
            requirements=tuple(requirements),
            planned_orders=tuple(planned_orders),
            alerts=tuple(alerts),
        )

    def _net_requirement(
        self,
        *,
        as_of: date,
        product_id: UUID,
        required_on: date,
        bucket: _RequirementBucket,
        available: Decimal,
        receipt_pool: Decimal,
        policy: MRPPlanningPolicy | None,
        order_sequence: int,
    ) -> tuple[
        MRPNetRequirement,
        MRPPlannedOrder | None,
        MRPPlanningAlert | None,
    ]:
        deficit = max(-available, Decimal("0"))
        available_pool = max(available, Decimal("0"))
        available_applied = min(available_pool, bucket.amount)
        available_pool -= available_applied
        remaining = bucket.amount - available_applied + deficit
        receipts_applied = min(receipt_pool, remaining)
        net = remaining - receipts_applied
        source_ids = tuple(sorted(bucket.source_ids, key=lambda value: value.hex))
        order = None
        alert = None
        planned_amount = Decimal("0")
        if net > 0:
            if policy is None:
                raise MRPPolicyNotFoundError(
                    f"no planning policy exists for product {product_id}."
                )
            quantity = policy.size(net, bucket.unit)
            planned_amount = quantity.amount
            release_on = required_on - timedelta(days=policy.lead_time_days)
            order_id = uuid5(
                self.company_id,
                "|".join(
                    (
                        str(order_sequence),
                        str(product_id),
                        required_on.isoformat(),
                        str(quantity.amount),
                    )
                ),
            )
            order = MRPPlannedOrder(
                id=order_id,
                company_id=self.company_id,
                order_type=(
                    MRPPlannedOrderType.MANUFACTURE
                    if policy.supply_mode is MRPSupplyMode.MAKE
                    else MRPPlannedOrderType.PURCHASE
                ),
                product_id=product_id,
                quantity=quantity,
                due_on=required_on,
                release_on=release_on,
                source_ids=source_ids,
            )
            available_pool += planned_amount - net
            if release_on < as_of:
                alert = MRPPlanningAlert(
                    company_id=self.company_id,
                    kind=MRPAlertKind.LEAD_TIME_CONSTRAINT,
                    planned_order_id=order_id,
                    product_id=product_id,
                    required_on=required_on,
                    calculated_release_on=release_on,
                    days_past_due=(as_of - release_on).days,
                )
        line = MRPNetRequirement(
            company_id=self.company_id,
            product_id=product_id,
            required_on=required_on,
            unit=bucket.unit,
            gross_amount=bucket.amount,
            available_applied=available_applied,
            scheduled_receipts_applied=receipts_applied,
            net_amount=net,
            planned_receipt_amount=planned_amount,
            projected_available=(
                available_pool + receipt_pool - receipts_applied
            ),
            source_ids=source_ids,
        )
        return line, order, alert

    def _explode_planned_order(
        self,
        order: MRPPlannedOrder,
        catalogue: dict[UUID, BillOfMaterials],
        gross: dict[UUID, dict[date, _RequirementBucket]],
    ) -> None:
        bom = catalogue.get(order.product_id)
        if bom is None:
            raise BomNotFoundError(
                "manufactured planned order requires an active BOM."
            )
        if not self._effective(bom, order.due_on):
            raise EngineeringUnavailableError(
                "manufactured planned order requires effective engineering."
            )
        self._require_unit(
            order.quantity.unit,
            bom.output_quantity.unit,
            "manufactured requirement",
        )
        factor = order.quantity.amount / bom.output_quantity.amount
        for item in bom.items:
            component = item.quantity_per_output.scaled_by(factor)
            gross_component = item.scrap_rate.gross_requirement(component)
            self._add_requirement(
                gross,
                product_id=item.component_product_id,
                required_on=order.release_on,
                unit=gross_component.unit,
                amount=gross_component.amount,
                source_id=order.id,
            )

    def _validate_inputs(
        self,
        demands: tuple[MRPDemand, ...],
        inventory: tuple[MRPInventoryPosition, ...],
        receipts: tuple[MRPScheduledReceipt, ...],
    ) -> None:
        self._typed_tuple(demands, MRPDemand, "demands", allow_empty=False)
        self._typed_tuple(inventory, MRPInventoryPosition, "inventory")
        self._typed_tuple(receipts, MRPScheduledReceipt, "scheduled_receipts")
        if (
            any(value.company_id != self.company_id for value in demands)
            or any(value.company_id != self.company_id for value in inventory)
            or any(value.company_id != self.company_id for value in receipts)
        ):
            raise ProductionScopeError("MRP plan inputs must belong to the engine company.")
        self._require_unique(
            tuple(value.source_id for value in demands),
            "demand source identifiers must be unique",
        )
        self._require_unique(
            tuple(value.product_id for value in inventory),
            "inventory positions must be unique per product",
        )
        self._require_unique(
            tuple(value.receipt_id for value in receipts),
            "scheduled receipt identifiers must be unique",
        )

    @staticmethod
    def _typed_tuple(
        values: tuple[object, ...],
        kind: type,
        field: str,
        *,
        allow_empty: bool = True,
    ) -> None:
        if not isinstance(values, tuple) or (not allow_empty and not values) or any(
            not isinstance(value, kind) for value in values
        ):
            qualifier = "non-empty " if not allow_empty else ""
            raise InvalidProductionValueError(
                f"{field} must be a {qualifier}tuple of {kind.__name__} values."
            )

    @staticmethod
    def _require_unique(values: tuple[UUID, ...], message: str) -> None:
        if len(values) != len(set(values)):
            raise InvalidProductionValueError(f"{message}.")

    @staticmethod
    def _date(value: date, field: str) -> None:
        if type(value) is not date:
            raise InvalidProductionValueError(f"{field} must be a date.")

    @staticmethod
    def _require_unit(
        actual: UnitOfMeasure,
        expected: UnitOfMeasure,
        subject: str,
    ) -> None:
        if actual is not expected:
            raise UnitOfMeasureMismatchError(
                f"{subject} unit does not match the gross requirement."
            )

    @staticmethod
    def _effective(bom: BillOfMaterials, on_date: date) -> bool:
        return bom.version.effective_from <= on_date and (
            bom.version.effective_until is None
            or on_date <= bom.version.effective_until
        )

    @staticmethod
    def _add_requirement(
        gross: dict[UUID, dict[date, _RequirementBucket]],
        *,
        product_id: UUID,
        required_on: date,
        unit: UnitOfMeasure,
        amount: Decimal,
        source_id: UUID,
    ) -> None:
        periods = gross.setdefault(product_id, {})
        bucket = periods.get(required_on)
        if bucket is None:
            periods[required_on] = _RequirementBucket(unit, amount, {source_id})
            return
        if bucket.unit is not unit:
            raise UnitOfMeasureMismatchError(
                "one product cannot have gross requirements in different units."
            )
        bucket.amount += amount
        bucket.source_ids.add(source_id)

    @staticmethod
    def _receipt_catalogue(
        receipts: tuple[MRPScheduledReceipt, ...],
    ) -> dict[UUID, tuple[MRPScheduledReceipt, ...]]:
        grouped: dict[UUID, list[MRPScheduledReceipt]] = {}
        for receipt in receipts:
            grouped.setdefault(receipt.product_id, []).append(receipt)
        return {
            product_id: tuple(
                sorted(
                    values,
                    key=lambda value: (value.available_on, value.receipt_id.hex),
                )
            )
            for product_id, values in grouped.items()
        }

    @staticmethod
    def _initial_available(
        position: MRPInventoryPosition | None,
        unit: UnitOfMeasure,
    ) -> Decimal:
        if position is None:
            return Decimal("0")
        MRPEngine._require_unit(position.unit, unit, "inventory position")
        return position.net_available

    @staticmethod
    def _low_level_codes(
        roots: tuple[UUID, ...],
        catalogue: dict[UUID, BillOfMaterials],
    ) -> dict[UUID, int]:
        levels: dict[UUID, int] = {}

        def visit(product_id: UUID, level: int) -> None:
            previous = levels.get(product_id, -1)
            if level <= previous:
                return
            levels[product_id] = level
            bom = catalogue.get(product_id)
            if bom is None:
                return
            for item in bom.items:
                visit(item.component_product_id, level + 1)

        for product_id in roots:
            visit(product_id, 0)
        return levels


__all__ = ["MRPEngine"]

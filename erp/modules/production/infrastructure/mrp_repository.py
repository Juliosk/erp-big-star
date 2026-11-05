"""Tenant-bound persistence for reproducible MRP executions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.application.mrp import MRPRun
from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    EngineeringVersion,
    MRPAlertKind,
    MRPDemand,
    MRPDemandSource,
    MRPInventoryPosition,
    MRPNetRequirement,
    MRPPlan,
    MRPPlannedOrder,
    MRPPlannedOrderType,
    MRPPlanningAlert,
    MRPPlanningPolicy,
    MRPScheduledReceipt,
    MRPScheduledReceiptType,
    MRPSupplyMode,
    ProductionConflictError,
    ProductionQuantity,
    ProductionScopeError,
    ScrapRate,
    UnitOfMeasure,
)
from erp.modules.production.infrastructure.mrp_model import (
    MRPPlannedOrderModel,
    MRPRunHistoryModel,
)

JsonObject = dict[str, Any]


class MRPRunRepository:
    """Persist MRP history without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, run: MRPRun, *, actor_id: UUID) -> None:
        self._validate_write(run, actor_id)
        if run.record_version != 1:
            raise ValueError("A new MRP run must start at record_version one.")
        self._session.add(
            MRPRunHistoryModel(
                id=run.id,
                company_id=run.company_id,
                as_of=run.as_of,
                horizon_end=run.horizon_end,
                status="COMPLETED",
                engine_version=run.engine_version,
                demand_count=len(run.plan.demands),
                requirement_count=len(run.plan.requirements),
                planned_order_count=len(run.plan.planned_orders),
                alert_count=len(run.plan.alerts),
                input_snapshot=_input_snapshot(run),
                result_snapshot=_result_snapshot(run.plan),
                started_at=run.started_at,
                completed_at=run.completed_at,
                version=run.record_version,
                created_at=run.completed_at,
                created_by=actor_id,
            )
        )
        await self._flush()
        self._session.add_all(
            [
                MRPPlannedOrderModel(
                    id=order.id,
                    company_id=run.company_id,
                    mrp_run_id=run.id,
                    sequence=sequence,
                    order_type=order.order_type.value,
                    status="PLANNED",
                    product_id=order.product_id,
                    quantity=order.quantity.amount,
                    uom=order.quantity.unit.value,
                    due_on=order.due_on,
                    release_on=order.release_on,
                    source_ids=[str(value) for value in order.source_ids],
                    version=1,
                    created_at=run.completed_at,
                    created_by=actor_id,
                )
                for sequence, order in enumerate(run.plan.planned_orders, start=1)
            ]
        )
        await self._flush()

    async def get(self, run_id: UUID) -> MRPRun | None:
        _nonzero_uuid(run_id, "run_id")
        header = await self._session.scalar(
            select(MRPRunHistoryModel)
            .where(
                MRPRunHistoryModel.company_id == self._company_id,
                MRPRunHistoryModel.id == run_id,
            )
            .execution_options(populate_existing=True)
        )
        if header is None:
            return None
        orders = await self._session.scalars(
            select(MRPPlannedOrderModel)
            .where(
                MRPPlannedOrderModel.company_id == self._company_id,
                MRPPlannedOrderModel.mrp_run_id == run_id,
            )
            .order_by(MRPPlannedOrderModel.sequence)
            .execution_options(populate_existing=True)
        )
        return _run(header, tuple(orders))

    async def planned_orders(self, run_id: UUID) -> tuple[MRPPlannedOrder, ...]:
        """Return normalized proposals ready for a future conversion use case."""
        run = await self.get(run_id)
        return () if run is None else run.plan.planned_orders

    def _validate_write(self, run: MRPRun, actor_id: UUID) -> None:
        if not isinstance(run, MRPRun):
            raise TypeError("run must be an MRPRun.")
        if run.company_id != self._company_id:
            raise ProductionScopeError("MRP run is outside the selected company.")
        _nonzero_uuid(actor_id, "actor_id")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505"}:
                raise ProductionConflictError(
                    "MRP run or planned order conflicts with persisted tenant data."
                ) from error
            raise


def _run(
    header: MRPRunHistoryModel,
    orders: tuple[MRPPlannedOrderModel, ...],
) -> MRPRun:
    inputs = cast(Mapping[str, Any], header.input_snapshot)
    results = cast(Mapping[str, Any], header.result_snapshot)
    demands = tuple(_demand(value) for value in _records(inputs, "demands"))
    inventory = tuple(_inventory(value) for value in _records(inputs, "inventory"))
    receipts = tuple(
        _scheduled_receipt(value) for value in _records(inputs, "scheduled_receipts")
    )
    boms = tuple(_bom(value) for value in _records(inputs, "boms"))
    policies = tuple(_policy(value) for value in _records(inputs, "policies"))
    plan = MRPPlan(
        company_id=header.company_id,
        as_of=header.as_of,
        demands=demands,
        requirements=tuple(
            _requirement(value) for value in _records(results, "requirements")
        ),
        planned_orders=tuple(_planned_order(value) for value in orders),
        alerts=tuple(_alert(value) for value in _records(results, "alerts")),
    )
    return MRPRun(
        id=header.id,
        company_id=header.company_id,
        as_of=header.as_of,
        horizon_end=header.horizon_end,
        started_at=header.started_at,
        completed_at=header.completed_at,
        plan=plan,
        inventory=inventory,
        scheduled_receipts=receipts,
        boms=boms,
        policies=policies,
        engine_version=header.engine_version,
        record_version=header.version,
    )


def _input_snapshot(run: MRPRun) -> JsonObject:
    return {
        "demands": [_demand_payload(value) for value in run.plan.demands],
        "inventory": [_inventory_payload(value) for value in run.inventory],
        "scheduled_receipts": [
            _scheduled_receipt_payload(value) for value in run.scheduled_receipts
        ],
        "boms": [_bom_payload(value) for value in run.boms],
        "policies": [_policy_payload(value) for value in run.policies],
    }


def _result_snapshot(plan: MRPPlan) -> JsonObject:
    return {
        "requirements": [_requirement_payload(value) for value in plan.requirements],
        "alerts": [_alert_payload(value) for value in plan.alerts],
    }


def _quantity_payload(value: ProductionQuantity) -> JsonObject:
    return {"amount": str(value.amount), "unit": value.unit.value}


def _quantity(value: Mapping[str, Any]) -> ProductionQuantity:
    return ProductionQuantity(Decimal(str(value["amount"])), UnitOfMeasure(str(value["unit"])))


def _demand_payload(value: MRPDemand) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "source_id": str(value.source_id),
        "source": value.source.value,
        "product_id": str(value.product_id),
        "quantity": _quantity_payload(value.quantity),
        "required_on": value.required_on.isoformat(),
    }


def _demand(value: Mapping[str, Any]) -> MRPDemand:
    return MRPDemand(
        company_id=UUID(str(value["company_id"])),
        source_id=UUID(str(value["source_id"])),
        source=MRPDemandSource(str(value["source"])),
        product_id=UUID(str(value["product_id"])),
        quantity=_quantity(_object(value, "quantity")),
        required_on=date.fromisoformat(str(value["required_on"])),
    )


def _inventory_payload(value: MRPInventoryPosition) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "product_id": str(value.product_id),
        "unit": value.unit.value,
        "on_hand": str(value.on_hand),
        "allocated": str(value.allocated),
        "safety_stock": str(value.safety_stock),
    }


def _inventory(value: Mapping[str, Any]) -> MRPInventoryPosition:
    return MRPInventoryPosition(
        company_id=UUID(str(value["company_id"])),
        product_id=UUID(str(value["product_id"])),
        unit=UnitOfMeasure(str(value["unit"])),
        on_hand=Decimal(str(value["on_hand"])),
        allocated=Decimal(str(value["allocated"])),
        safety_stock=Decimal(str(value["safety_stock"])),
    )


def _scheduled_receipt_payload(value: MRPScheduledReceipt) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "receipt_id": str(value.receipt_id),
        "receipt_type": value.receipt_type.value,
        "product_id": str(value.product_id),
        "quantity": _quantity_payload(value.quantity),
        "available_on": value.available_on.isoformat(),
    }


def _scheduled_receipt(value: Mapping[str, Any]) -> MRPScheduledReceipt:
    return MRPScheduledReceipt(
        company_id=UUID(str(value["company_id"])),
        receipt_id=UUID(str(value["receipt_id"])),
        receipt_type=MRPScheduledReceiptType(str(value["receipt_type"])),
        product_id=UUID(str(value["product_id"])),
        quantity=_quantity(_object(value, "quantity")),
        available_on=date.fromisoformat(str(value["available_on"])),
    )


def _bom_payload(value: BillOfMaterials) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "product_id": str(value.product_id),
        "version": {
            "code": value.version.code,
            "revision": value.version.revision,
            "effective_from": value.version.effective_from.isoformat(),
            "effective_until": (
                value.version.effective_until.isoformat()
                if value.version.effective_until is not None
                else None
            ),
        },
        "output_quantity": _quantity_payload(value.output_quantity),
        "items": [
            {
                "component_product_id": str(item.component_product_id),
                "quantity_per_output": _quantity_payload(item.quantity_per_output),
                "scrap_rate": str(item.scrap_rate.value),
            }
            for item in value.items
        ],
        "record_version": value.record_version,
    }


def _bom(value: Mapping[str, Any]) -> BillOfMaterials:
    version = _object(value, "version")
    effective_until = version.get("effective_until")
    return BillOfMaterials(
        company_id=UUID(str(value["company_id"])),
        product_id=UUID(str(value["product_id"])),
        version=EngineeringVersion(
            code=str(version["code"]),
            revision=int(version["revision"]),
            effective_from=date.fromisoformat(str(version["effective_from"])),
            effective_until=(
                date.fromisoformat(str(effective_until))
                if effective_until is not None
                else None
            ),
        ),
        output_quantity=_quantity(_object(value, "output_quantity")),
        items=tuple(
            BomItem(
                component_product_id=UUID(str(item["component_product_id"])),
                quantity_per_output=_quantity(_object(item, "quantity_per_output")),
                scrap_rate=ScrapRate(Decimal(str(item["scrap_rate"]))),
            )
            for item in _records(value, "items")
        ),
        record_version=int(value["record_version"]),
    )


def _policy_payload(value: MRPPlanningPolicy) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "product_id": str(value.product_id),
        "supply_mode": value.supply_mode.value,
        "minimum_lot": _quantity_payload(value.minimum_lot),
        "lead_time_days": value.lead_time_days,
        "lot_multiple": (
            _quantity_payload(value.lot_multiple)
            if value.lot_multiple is not None
            else None
        ),
    }


def _policy(value: Mapping[str, Any]) -> MRPPlanningPolicy:
    multiple = value.get("lot_multiple")
    return MRPPlanningPolicy(
        company_id=UUID(str(value["company_id"])),
        product_id=UUID(str(value["product_id"])),
        supply_mode=MRPSupplyMode(str(value["supply_mode"])),
        minimum_lot=_quantity(_object(value, "minimum_lot")),
        lead_time_days=int(value["lead_time_days"]),
        lot_multiple=(
            _quantity(cast(Mapping[str, Any], multiple))
            if multiple is not None
            else None
        ),
    )


def _requirement_payload(value: MRPNetRequirement) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "product_id": str(value.product_id),
        "required_on": value.required_on.isoformat(),
        "unit": value.unit.value,
        "gross_amount": str(value.gross_amount),
        "available_applied": str(value.available_applied),
        "scheduled_receipts_applied": str(value.scheduled_receipts_applied),
        "net_amount": str(value.net_amount),
        "planned_receipt_amount": str(value.planned_receipt_amount),
        "projected_available": str(value.projected_available),
        "source_ids": [str(item) for item in value.source_ids],
    }


def _requirement(value: Mapping[str, Any]) -> MRPNetRequirement:
    return MRPNetRequirement(
        company_id=UUID(str(value["company_id"])),
        product_id=UUID(str(value["product_id"])),
        required_on=date.fromisoformat(str(value["required_on"])),
        unit=UnitOfMeasure(str(value["unit"])),
        gross_amount=Decimal(str(value["gross_amount"])),
        available_applied=Decimal(str(value["available_applied"])),
        scheduled_receipts_applied=Decimal(str(value["scheduled_receipts_applied"])),
        net_amount=Decimal(str(value["net_amount"])),
        planned_receipt_amount=Decimal(str(value["planned_receipt_amount"])),
        projected_available=Decimal(str(value["projected_available"])),
        source_ids=tuple(UUID(str(item)) for item in _values(value, "source_ids")),
    )


def _planned_order(value: MRPPlannedOrderModel) -> MRPPlannedOrder:
    return MRPPlannedOrder(
        id=value.id,
        company_id=value.company_id,
        order_type=MRPPlannedOrderType(value.order_type),
        product_id=value.product_id,
        quantity=ProductionQuantity(value.quantity, UnitOfMeasure(value.uom)),
        due_on=value.due_on,
        release_on=value.release_on,
        source_ids=tuple(UUID(item) for item in value.source_ids),
    )


def _alert_payload(value: MRPPlanningAlert) -> JsonObject:
    return {
        "company_id": str(value.company_id),
        "kind": value.kind.value,
        "planned_order_id": str(value.planned_order_id),
        "product_id": str(value.product_id),
        "required_on": value.required_on.isoformat(),
        "calculated_release_on": value.calculated_release_on.isoformat(),
        "days_past_due": value.days_past_due,
    }


def _alert(value: Mapping[str, Any]) -> MRPPlanningAlert:
    return MRPPlanningAlert(
        company_id=UUID(str(value["company_id"])),
        kind=MRPAlertKind(str(value["kind"])),
        planned_order_id=UUID(str(value["planned_order_id"])),
        product_id=UUID(str(value["product_id"])),
        required_on=date.fromisoformat(str(value["required_on"])),
        calculated_release_on=date.fromisoformat(
            str(value["calculated_release_on"])
        ),
        days_past_due=int(value["days_past_due"]),
    )


def _records(value: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    raw = value[key]
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise ProductionConflictError(f"MRP snapshot field {key} is corrupted.")
    return tuple(cast(Mapping[str, Any], item) for item in raw)


def _values(value: Mapping[str, Any], key: str) -> tuple[Any, ...]:
    raw = value[key]
    if not isinstance(raw, list):
        raise ProductionConflictError(f"MRP snapshot field {key} is corrupted.")
    return tuple(raw)


def _object(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = value[key]
    if not isinstance(raw, Mapping):
        raise ProductionConflictError(f"MRP snapshot field {key} is corrupted.")
    return cast(Mapping[str, Any], raw)


def _nonzero_uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field} must be a non-zero UUID.")
    return value


__all__ = ["MRPRunRepository"]

"""Tenant-bound repositories for the M5 physical inventory catalogue."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.admin.infrastructure.corporate_models import BranchModel
from erp.modules.inventory.domain import (
    InventoryLot,
    InventoryLotStatus,
    InventoryPool,
    InventoryPoolKind,
    Warehouse,
    WarehouseLocation,
)
from erp.modules.inventory.infrastructure.lot_model import InventoryLotModel
from erp.modules.inventory.infrastructure.pool_model import InventoryPoolModel
from erp.modules.inventory.infrastructure.warehouse_model import (
    WarehouseLocationModel,
    WarehouseModel,
)
from erp.modules.product.infrastructure.product_model import ProductModel
from erp.platform.errors import ApplicationError


def _require_company(company_id: UUID) -> None:
    if not isinstance(company_id, UUID):
        raise ValueError("An explicit company UUID is required.")


def _require_actor(actor_id: UUID) -> None:
    if not isinstance(actor_id, UUID):
        raise ValueError("An explicit actor UUID is required.")


def _duplicate(error: IntegrityError, *, resource: str) -> ApplicationError | None:
    if getattr(error.orig, "sqlstate", None) == "23505":
        return ApplicationError(
            code=f"INVENTORY_{resource.upper()}_CONFLICT",
            message=f"This inventory {resource.lower()} already exists for the selected company.",
            status_code=409,
        )
    return None


def _warehouse(model: WarehouseModel) -> Warehouse:
    return Warehouse(
        id=model.id,
        company_id=model.company_id,
        branch_id=model.branch_id,
        code=model.code,
        name=model.name,
        active=model.active,
        version=model.version,
    )


def _location(model: WarehouseLocationModel) -> WarehouseLocation:
    return WarehouseLocation(
        id=model.id,
        company_id=model.company_id,
        warehouse_id=model.warehouse_id,
        parent_location_id=model.parent_location_id,
        code=model.code,
        name=model.name,
        active=model.active,
        version=model.version,
    )


def _pool(model: InventoryPoolModel) -> InventoryPool:
    return InventoryPool(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        name=model.name,
        kind=InventoryPoolKind(model.kind),
        active=model.active,
        version=model.version,
    )


def _lot(model: InventoryLotModel) -> InventoryLot:
    return InventoryLot(
        id=model.id,
        company_id=model.company_id,
        product_id=model.product_id,
        code=model.code,
        status=InventoryLotStatus(model.status),
        expires_on=model.expires_on,
        version=model.version,
    )


class WarehouseRepository:
    """Warehouse persistence with an immutable company scope."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        _require_company(company_id)
        self._session = session
        self._company_id = company_id

    async def add(self, warehouse: Warehouse, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(warehouse.company_id)
        if warehouse.version != 1 or not warehouse.active:
            raise ValueError("A new warehouse must start active at version one.")
        branch_exists = await self._session.scalar(
            select(1)
            .select_from(BranchModel)
            .where(
                BranchModel.company_id == self._company_id,
                BranchModel.id == warehouse.branch_id,
            )
        )
        if branch_exists is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Branch not found.", status_code=404
            )
        self._session.add(
            WarehouseModel(
                id=warehouse.id,
                company_id=self._company_id,
                branch_id=warehouse.branch_id,
                code=warehouse.code,
                name=warehouse.name,
                active=warehouse.active,
                version=warehouse.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            conflict = _duplicate(error, resource="WAREHOUSE")
            if conflict is not None:
                raise conflict from error
            raise

    async def get(self, warehouse_id: UUID) -> Warehouse | None:
        result = await self._session.scalars(
            select(WarehouseModel)
            .where(
                WarehouseModel.company_id == self._company_id,
                WarehouseModel.id == warehouse_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _warehouse(model)

    async def list(
        self, *, limit: int = 50, offset: int = 0, active: bool | None = None
    ) -> tuple[Warehouse, ...]:
        _validate_page(limit, offset)
        statement = select(WarehouseModel).where(WarehouseModel.company_id == self._company_id)
        if active is not None:
            statement = statement.where(WarehouseModel.active == active)
        result = await self._session.scalars(
            statement.order_by(WarehouseModel.code, WarehouseModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_warehouse(model) for model in result)

    def _validate_scope(self, company_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The warehouse is outside the selected company.",
                status_code=403,
            )


class WarehouseLocationRepository:
    """Location persistence, including same-company parent validation."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        _require_company(company_id)
        self._session = session
        self._company_id = company_id

    async def add(self, location: WarehouseLocation, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(location.company_id)
        if location.version != 1 or not location.active:
            raise ValueError("A new location must start active at version one.")
        warehouse_exists = await self._session.scalar(
            select(WarehouseModel.id).where(
                WarehouseModel.company_id == self._company_id,
                WarehouseModel.id == location.warehouse_id,
            )
        )
        if warehouse_exists is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Warehouse not found.",
                status_code=404,
            )
        if location.parent_location_id is not None:
            parent = await self._session.scalar(
                select(WarehouseLocationModel).where(
                    WarehouseLocationModel.company_id == self._company_id,
                    WarehouseLocationModel.id == location.parent_location_id,
                )
            )
            if parent is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Parent location not found.",
                    status_code=404,
                )
            if parent.warehouse_id != location.warehouse_id:
                raise ApplicationError(
                    code="INVENTORY_LOCATION_WAREHOUSE_MISMATCH",
                    message="Parent location belongs to another warehouse.",
                    status_code=409,
                )
        self._session.add(
            WarehouseLocationModel(
                id=location.id,
                company_id=self._company_id,
                warehouse_id=location.warehouse_id,
                parent_location_id=location.parent_location_id,
                code=location.code,
                name=location.name,
                active=location.active,
                version=location.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            conflict = _duplicate(error, resource="LOCATION")
            if conflict is not None:
                raise conflict from error
            raise

    async def get(self, location_id: UUID) -> WarehouseLocation | None:
        result = await self._session.scalars(
            select(WarehouseLocationModel)
            .where(
                WarehouseLocationModel.company_id == self._company_id,
                WarehouseLocationModel.id == location_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _location(model)

    async def list(
        self,
        *,
        warehouse_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
        active: bool | None = None,
    ) -> tuple[WarehouseLocation, ...]:
        _validate_page(limit, offset)
        statement = select(WarehouseLocationModel).where(
            WarehouseLocationModel.company_id == self._company_id
        )
        if warehouse_id is not None:
            statement = statement.where(WarehouseLocationModel.warehouse_id == warehouse_id)
        if active is not None:
            statement = statement.where(WarehouseLocationModel.active == active)
        result = await self._session.scalars(
            statement.order_by(WarehouseLocationModel.code, WarehouseLocationModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_location(model) for model in result)

    def _validate_scope(self, company_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The location is outside the selected company.",
                status_code=403,
            )


class InventoryPoolRepository:
    """Company-scoped stock-pool persistence."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        _require_company(company_id)
        self._session = session
        self._company_id = company_id

    async def add(self, pool: InventoryPool, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(pool.company_id)
        if pool.version != 1 or not pool.active:
            raise ValueError("A new inventory pool must start active at version one.")
        self._session.add(
            InventoryPoolModel(
                id=pool.id,
                company_id=self._company_id,
                code=pool.code,
                name=pool.name,
                kind=pool.kind,
                active=pool.active,
                version=pool.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            conflict = _duplicate(error, resource="POOL")
            if conflict is not None:
                raise conflict from error
            raise

    async def get(self, pool_id: UUID) -> InventoryPool | None:
        result = await self._session.scalars(
            select(InventoryPoolModel)
            .where(
                InventoryPoolModel.company_id == self._company_id,
                InventoryPoolModel.id == pool_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _pool(model)

    async def list(
        self, *, limit: int = 50, offset: int = 0, active: bool | None = None
    ) -> tuple[InventoryPool, ...]:
        _validate_page(limit, offset)
        statement = select(InventoryPoolModel).where(
            InventoryPoolModel.company_id == self._company_id
        )
        if active is not None:
            statement = statement.where(InventoryPoolModel.active == active)
        result = await self._session.scalars(
            statement.order_by(InventoryPoolModel.code, InventoryPoolModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_pool(model) for model in result)

    def _validate_scope(self, company_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The inventory pool is outside the selected company.",
                status_code=403,
            )


class InventoryLotRepository:
    """Company/product-scoped lot persistence."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        _require_company(company_id)
        self._session = session
        self._company_id = company_id

    async def add(self, lot: InventoryLot, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(lot.company_id)
        if lot.version != 1 or lot.status is not InventoryLotStatus.OPEN:
            raise ValueError("A new inventory lot must start open at version one.")
        # The composite FK prevents cross-company references at the database
        # boundary; this lookup gives callers the stable 404 contract.
        product_exists = await self._session.scalar(
            select(1)
            .select_from(ProductModel)
            .where(
                ProductModel.company_id == self._company_id,
                ProductModel.id == lot.product_id,
            )
        )
        if product_exists is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Product not found.", status_code=404
            )
        self._session.add(
            InventoryLotModel(
                id=lot.id,
                company_id=self._company_id,
                product_id=lot.product_id,
                code=lot.code,
                status=lot.status,
                expires_on=lot.expires_on,
                version=lot.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            conflict = _duplicate(error, resource="LOT")
            if conflict is not None:
                raise conflict from error
            raise

    async def get(self, lot_id: UUID) -> InventoryLot | None:
        result = await self._session.scalars(
            select(InventoryLotModel)
            .where(
                InventoryLotModel.company_id == self._company_id,
                InventoryLotModel.id == lot_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _lot(model)

    async def list(
        self,
        *,
        product_id: UUID | None = None,
        status: InventoryLotStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[InventoryLot, ...]:
        _validate_page(limit, offset)
        statement = select(InventoryLotModel).where(
            InventoryLotModel.company_id == self._company_id
        )
        if product_id is not None:
            statement = statement.where(InventoryLotModel.product_id == product_id)
        if status is not None:
            statement = statement.where(InventoryLotModel.status == status)
        result = await self._session.scalars(
            statement.order_by(InventoryLotModel.code, InventoryLotModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_lot(model) for model in result)

    def _validate_scope(self, company_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The inventory lot is outside the selected company.",
                status_code=403,
            )


def _validate_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


# Short names are kept as public aliases for callers that treat the four
# physical records uniformly.
LocationRepository = WarehouseLocationRepository
PoolRepository = InventoryPoolRepository
LotRepository = InventoryLotRepository


__all__ = [
    "InventoryLotRepository",
    "InventoryPoolRepository",
    "LocationRepository",
    "LotRepository",
    "PoolRepository",
    "WarehouseLocationRepository",
    "WarehouseRepository",
    "_location",
    "_lot",
    "_pool",
    "_warehouse",
]
